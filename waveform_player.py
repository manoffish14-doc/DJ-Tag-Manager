"""Three-band RGB waveform visualization and macOS audio preview controls.

Uses a cached low-resolution STFT for drawing. Playback uses macOS afplay,
with seeking supported only if the installed afplay accepts -s.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time
import tkinter as tk
from tkinter import ttk


def waveform_bands(path, cache_dir, bins=850):
    import numpy as np
    import librosa
    source=Path(path)
    stat=source.stat()
    cache_dir=Path(cache_dir); cache_dir.mkdir(parents=True,exist_ok=True)
    key=hashlib.sha256(f'{source.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{bins}'.encode()).hexdigest()
    cache=cache_dir / (key+'.npz')
    if cache.exists():
        with np.load(cache) as data:
            return data['bands'].copy(),float(data['duration'])
    y,sr=librosa.load(str(source),sr=11025,mono=True)
    duration=len(y)/sr
    if not len(y): raise ValueError('Empty audio')
    hop=512
    spec=np.abs(librosa.stft(y,n_fft=2048,hop_length=hop))
    freqs=librosa.fft_frequencies(sr=sr,n_fft=2048)
    bands=np.zeros((3,bins),dtype=np.float32)
    frame_edges=np.linspace(0,spec.shape[1],bins+1).astype(int)
    for band,(low,high) in enumerate(((20,250),(250,2000),(2000,5500))):
        selected=spec[(freqs>=low)&(freqs<high)]
        if not selected.size:continue
        energy=np.sqrt(np.mean(selected**2,axis=0))
        for i in range(bins):
            start=frame_edges[i]; end=max(start+1,frame_edges[i+1]); end=min(end,len(energy))
            bands[band,i]=float(np.max(energy[start:end])) if start<len(energy) else 0
        scale=float(np.percentile(bands[band],98)) or 1
        bands[band]=np.clip(bands[band]/scale,0,1)
    np.savez_compressed(cache,bands=bands,duration=duration)
    # Avoid unbounded cache growth.
    files=sorted(cache_dir.glob('*.npz'),key=lambda p:p.stat().st_mtime,reverse=True)
    for old in files[200:]:
        try:old.unlink()
        except OSError:pass
    return bands,duration


class RGBWaveform(tk.Canvas):
    def __init__(self,parent,seek,**kwargs):
        super().__init__(parent,bg='#22262E',highlightthickness=0,height=44,**kwargs)
        self.seek=seek
        self.bands=None; self.duration=0; self.position=0; self.zoom=1
        self.cues=[]
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Button-1>',self._click)
        self.bind('<MouseWheel>',self._zoom)

    def _click(self,event):
        if self.duration:
            self.seek(max(0,min(self.duration,event.x/max(1,self.winfo_width())*self.duration/self.zoom)))

    def _zoom(self,event):
        self.zoom=max(1,min(8,self.zoom*(1.25 if event.delta>0 else .8)))
        self.draw()

    def draw(self):
        self.delete('all')
        w=max(1,self.winfo_width());h=max(1,self.winfo_height());mid=h/2
        if self.bands is None:
            self.create_text(w/2,mid,text='Load a track to display RGB waveform',fill='#A6B0BF')
            return
        import numpy as np
        bands=self.bands
        end=max(1,int(bands.shape[1]/self.zoom))
        colors=('#FF4B64','#40DDA5','#5F9CFF')
        for x in range(0,w,2):
            index=min(end-1,int(x/w*end))
            values=bands[:,index]
            height=max(2,float(np.max(values))*mid*.92)
            # Three bands overlay as colored nested envelopes.
            for j in (2,1,0):
                amplitude=max(1,float(values[j])*mid*.9)
                self.create_line(x,mid-amplitude,x,mid+amplitude,fill=colors[j],width=2)
        for cue in self.cues:
            sec=cue.get('seconds',0)
            if sec<=self.duration/self.zoom:
                x=sec/self.duration*self.zoom*w
                self.create_line(x,0,x,h,fill=cue.get('color','#FACC15'),width=2)
        if self.duration:
            x=self.position/self.duration*self.zoom*w
            if 0<=x<=w:self.create_line(x,0,x,h,fill='#FACC15',width=2)


class WaveformController:
    def __init__(self,app,bar):
        self.app=app
        self.position=0.;self.duration=0.;self.started=None;self.bands=None
        self.volume=tk.DoubleVar(value=.8)
        self.wave=RGBWaveform(bar,self.seek)
        self.wave.pack(side='left',fill='x',expand=True,padx=6)
        self.clock=tk.Label(bar,text='0:00 / 0:00',bg='#292D35',fg='#F5F5F5',font=('Helvetica',10))
        self.clock.pack(side='left',padx=5)
        ttk.Scale(bar,from_=0,to=1,variable=self.volume,orient='horizontal',length=75,command=self._volume).pack(side='right',padx=6)
        self.expand_button=tk.Button(bar,text='↗',bg='#292D35',fg='#FACC15',borderwidth=0,command=self.expand)
        self.expand_button.pack(side='right')
        self.expanded=None
        self.seek_supported=None
        self._probe_seek()
        self.app.root.after(180,self.tick)

    def _probe_seek(self):
        try:
            result=subprocess.run(['/usr/bin/afplay','-h'],capture_output=True,text=True,timeout=2)
            self.seek_supported='-s ' in (result.stdout+result.stderr)
        except Exception:self.seek_supported=False

    def _volume(self,_=None):
        # afplay volume is specified at process startup; apply on next seek/play.
        pass

    def load(self,path):
        self.position=0.;self.duration=float(self.app.rows.get(path,{}).get('duration') or 0)
        self.wave.bands=None;self.wave.duration=self.duration;self.wave.position=0;self.wave.draw()
        if self.expanded:self.expanded.bands=None;self.expanded.draw()
        try:self.wave.cues=self.app.store.cues(path)
        except Exception:self.wave.cues=[]
        def worker():
            try:bands,duration=waveform_bands(path,self.app.data_dir/'waveforms')
            except Exception:return
            self.app.events.put(('waveform_ready',path,bands,duration))
        threading.Thread(target=worker,daemon=True).start()

    def ready(self,path,bands,duration):
        if path!=self.app.player_path:return
        self.bands=bands;self.duration=duration
        for wave in (self.wave,self.expanded):
            if wave:
                wave.bands=bands;wave.duration=duration;wave.cues=self.wave.cues;wave.draw()

    def seek(self,seconds):
        seconds=max(0,min(float(seconds),self.duration))
        if not self.seek_supported:
            self.app.status.configure(text='This macOS afplay version does not support seeking.')
            return
        self.app._launch_playback(seconds)

    def tick(self):
        if self.started is not None and self.app.player_process and self.app.player_process.poll() is None:
            self.position=min(self.duration,self.position+0) if False else min(self.duration,self.start_position+time.monotonic()-self.started)
        m,s=divmod(int(self.position),60); dm,ds=divmod(int(self.duration),60)
        self.clock.configure(text=f'{m}:{s:02d} / {dm}:{ds:02d}')
        self.wave.position=self.position;self.wave.draw()
        if self.expanded:self.expanded.position=self.position;self.expanded.draw()
        self.app.root.after(180,self.tick)

    def expand(self):
        if self.expanded:
            try:self.expanded.winfo_toplevel().destroy()
            except tk.TclError:pass
            self.expanded=None;return
        win=tk.Toplevel(self.app.root);win.title('RGB Waveform — Scroll to Zoom');win.geometry('1000x270')
        wave=RGBWaveform(win,self.seek,height=185)
        wave.pack(fill='both',expand=True,padx=12,pady=12)
        wave.bands=self.bands;wave.duration=self.duration;wave.cues=self.wave.cues;wave.draw()
        self.expanded=wave
        win.protocol('WM_DELETE_WINDOW',lambda:(setattr(self,'expanded',None),win.destroy()))
