"""Additional Settings, filter, queue and backup UI for the v3 development build."""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from task_queue import DurableQueue


class IntegratedWorkflows:
    def setup_integrated(self):
        self.queue_engine=DurableQueue(self.data_dir/'tasks.sqlite3',self._queue_execute,self.events.put)
        self.queue_visible=False
        self.task_bar=ttk.Frame(self.root)
        self.task_label=ttk.Label(self.task_bar,text='Tasks')
        self.task_label.pack(side='left',padx=8)
        ttk.Button(self.task_bar,text='Queue…',command=self.queue_dialog).pack(side='right',padx=5)
        self.task_bar.pack(fill='x',before=self.status)
        self._last_backup=None
        self.root.after(3000,self._backup_tick)
        self.root.after(700,self._queue_tick)
        self._build_sidebar_additions()
        self._install_shortcuts()

    def _queue_execute(self,kind,path):
        from metadata_sources import lookup as multi_lookup
        from app import analyze_cues
        if kind in ('lookup','lookup_analyze'):
            r=self.rows.get(path,{})
            found=multi_lookup(r.get('suggested_artist') or r.get('artist',''),r.get('suggested_title') or r.get('title',''),self.config)
            if kind=='lookup_analyze':
                from metadata_automation import analyze_audio
                try: analysis=analyze_audio(path)
                except Exception as exc: analysis={'error':type(exc).__name__}
                return {'lookup':found,'analysis':analysis}
            return found
        if kind=='analyze_metadata':
            from metadata_automation import analyze_audio
            return analyze_audio(path)
        if kind=='analyze':return analyze_cues(path)
        if kind=='key':
            import librosa
            import numpy as np
            from app import detect_key
            return detect_key(path)
        raise ValueError('Unknown queued job: '+kind)

    def _queue_tick(self):
        if not self.root.winfo_exists():return
        try:
            snapshot=self.queue_engine.snapshot(40)
            active=[j for j in snapshot if j['state'] in ('waiting','running')]
            if active:
                running=next((j for j in active if j['state']=='running'),active[0])
                self.task_label.configure(text=f"{self._task_name(running['kind'])} · {running['cursor']}/{running['total']} tracks · {len(active)} queued/running · {'Paused' if self.queue_engine.paused else 'Active'}")
            else:self.task_label.configure(text='Background Operations · Ready')
        except Exception:pass
        self.root.after(700,self._queue_tick)

    @staticmethod
    def _task_name(kind):
        return {'lookup':'Finding Tags & Art','lookup_analyze':'Finding Tags & Art + Audio Analysis','analyze':'Analyzing BPM','analyze_metadata':'Analyzing BPM & Key'}.get(kind, kind.replace('_',' ').title())

    def queue_dialog(self):
        win=tk.Toplevel(self.root);win.title('Background Task Queue');win.geometry('850x530')
        holder=ttk.Frame(win,padding=12);holder.pack(fill='both',expand=True)
        tree=ttk.Treeview(holder,columns=('kind','progress','state','success','errors'),show='headings')
        for col,width in [('kind',135),('progress',120),('state',110),('success',110),('errors',120)]:
            tree.heading(col,text=col.title());tree.column(col,width=width)
        tree.pack(fill='both',expand=True)
        def refresh():
            if not win.winfo_exists():return
            rows=self.queue_engine.snapshot()
            tree.delete(*tree.get_children())
            for j in rows:
                tree.insert('','end',iid=str(j['id']),values=(self._task_name(j['kind']),f"{j['cursor']}/{j['total']}",j['state'],j['successes'],len(j['errors'])))
            win.after(1000,refresh)
        refresh()
        controls=ttk.Frame(holder);controls.pack(fill='x',pady=10)
        ttk.Button(controls,text='Pause / Resume',command=lambda:self.queue_engine.pause(not self.queue_engine.paused)).pack(side='left',padx=3)
        def selected_id():return int(tree.selection()[0]) if tree.selection() else None
        ttk.Button(controls,text='Cancel Selected',command=lambda:self.queue_engine.cancel(selected_id()) if selected_id() else None).pack(side='left',padx=3)
        ttk.Button(controls,text='Move Up',command=lambda:self.queue_engine.move(selected_id(),-1) if selected_id() else None).pack(side='left',padx=3)
        ttk.Button(controls,text='Move Down',command=lambda:self.queue_engine.move(selected_id(),1) if selected_id() else None).pack(side='left',padx=3)
        ttk.Label(holder,text='Cancel marks the task immediately. An in-flight network request may take up to its timeout to stop; cancelled results are discarded.',style='Muted.TLabel').pack(anchor='w')

    def _build_sidebar_additions(self):
        for name,fn in [('Advanced Settings',self.advanced_settings),('Smart Filter Builder',self.smart_filter_builder),('Task Queue',self.queue_dialog),('Backup Now',self.backup_now),('Metadata Write History',self.metadata_write_history_dialog)]:
            tk.Button(self.sidebar,text=name,anchor='w',bg='#15171B',fg='#F5F5F5',borderwidth=0,padx=14,pady=6,command=fn).pack(fill='x')

    def _backup_destination(self):
        custom=self.extra_settings.get('backup_folder','')
        if custom:
            dest=Path(custom).expanduser()
            if dest.is_dir() and os.access(dest,os.W_OK):return dest
        dest=self.data_dir/'backups';dest.mkdir(parents=True,exist_ok=True)
        return dest

    def backup_now(self,quiet=False):
        dest=self._backup_destination()
        timestamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        target=dest/f'backup-{timestamp}'
        target.mkdir(parents=True)
        files=[self.library_file,self.preferences_path,self.layout_path,self.data_dir/'v3_combined.sqlite3',self.data_dir/'tasks.sqlite3']
        copied=[]
        for file in files:
            if file.exists():
                if file.suffix=='.sqlite3':
                    with sqlite3.connect(file) as src,sqlite3.connect(target/file.name) as out:src.backup(out)
                else:shutil.copy2(file,target/file.name)
                copied.append(file.name)
        (target/'manifest.json').write_text(json.dumps({'created':datetime.now(timezone.utc).isoformat(),'files':copied},indent=2))
        self._last_backup=datetime.now()
        self._rotate_backups(dest)
        if not quiet:messagebox.showinfo('Backup',f'Backup saved to {target}\nMusic files are not copied.')
        return target

    def _rotate_backups(self,dest):
        backups=sorted((p for p in dest.glob('backup-*') if p.is_dir()),reverse=True)
        keep=set();weeks=set()
        for p in backups:
            try:dt=datetime.strptime(p.name[7:22],'%Y%m%d-%H%M%S')
            except ValueError:continue
            if len(keep)<14:keep.add(p);continue
            week=dt.isocalendar()[:2]
            if week not in weeks and len(weeks)<4:weeks.add(week);keep.add(p)
        for p in backups:
            if p not in keep:shutil.rmtree(p)

    def _backup_tick(self):
        if not self.root.winfo_exists():return
        if self.extra_settings.get('auto_backups',True):
            now=datetime.now()
            if self._last_backup is None or (now-self._last_backup).total_seconds()>86400:
                try:self.backup_now(quiet=True)
                except Exception as exc:self.status.configure(text=f'Automatic backup failed: {exc}')
        self.root.after(60*60*1000,self._backup_tick)

    def advanced_settings(self):
        win=tk.Toplevel(self.root);win.title('Settings — DJ Tag Manager');win.geometry('850x620')
        nav=tk.Frame(win,bg='#15171B',width=180);nav.pack(side='left',fill='y');nav.pack_propagate(False)
        body=ttk.Frame(win,padding=22);body.pack(side='left',fill='both',expand=True)
        def page(name):
            for child in body.winfo_children():child.destroy()
            ttk.Label(body,text=name,font=('Helvetica',19,'bold')).pack(anchor='w',pady=(0,18))
            self.extra_settings['last_category']=name;self.save_preferences()
            def toggle(label,key,default=False):
                var=tk.BooleanVar(value=self.extra_settings.get(key,default))
                ttk.Checkbutton(body,text=label,variable=var,command=lambda:self._setting(key,var.get())).pack(anchor='w',pady=8)
            if name=='General':
                toggle('Restore previous workspace', 'restore_workspace',True)
                toggle('Show descriptive tooltips','tooltips',True)
            elif name=='Library':
                ttk.Label(body,text='Low bitrate threshold (kbps)').pack(anchor='w')
                var=tk.StringVar(value=str(self.extra_settings.get('low_bitrate',320)))
                ent=ttk.Entry(body,textvariable=var);ent.pack(anchor='w')
                def save():
                    try:self._setting('low_bitrate',max(1,int(var.get())))
                    except ValueError:messagebox.showerror('Settings','Enter a positive integer.')
                ttk.Button(body,text='Apply',command=save).pack(anchor='w',pady=8)
            elif name=='Metadata':
                ttk.Label(body,text='Metadata lookup and audio analysis remain manual.').pack(anchor='w')
                ttk.Button(body,text='Provider API Keys',command=self.settings).pack(anchor='w',pady=8)
            elif name=='Audio':
                ttk.Label(body,text='RGB waveform: bass red, mid green, treble blue. Scroll expanded waveform to zoom.').pack(anchor='w')
                toggle('Show cue markers','cue_markers',True)
            elif name=='Appearance':
                toggle('Show compact statistics','compact_stats',True)
                ttk.Label(body,text='Charcoal and yellow appearance is currently fixed.').pack(anchor='w')
            elif name=='Backups':
                toggle('Automatic daily backups while app is running','auto_backups',True)
                ttk.Label(body,text='Backup folder (empty = Application Support)').pack(anchor='w')
                var=tk.StringVar(value=self.extra_settings.get('backup_folder',''))
                ttk.Entry(body,textvariable=var).pack(fill='x',pady=5)
                def choose():
                    folder=filedialog.askdirectory(parent=win)
                    if folder:var.set(folder);self._setting('backup_folder',folder)
                ttk.Button(body,text='Choose Folder',command=choose).pack(anchor='w')
                ttk.Button(body,text='Backup Now',command=self.backup_now).pack(anchor='w',pady=8)
                ttk.Button(body,text='Restore Backup',command=self.restore_integrated_backup).pack(anchor='w')
            elif name=='Updates':
                toggle('Notify when updates are available','update_notifications',True)
                ttk.Label(body,text='Automatic install is disabled in this development build.').pack(anchor='w')
            elif name=='Keyboard Shortcuts':
                ttk.Label(body,text='⌘Z Undo · ⌘⇧Z Redo · ⌘F Search · ⌘O Import · Space Play/Pause · 1–8 Hot Cues').pack(anchor='w')
                self._shortcut_settings_page(body)
            elif name=='Serato':self.serato_settings()
        for name in ('General','Library','Metadata','Audio','Appearance','Backups','Updates','Keyboard Shortcuts','Serato'):
            tk.Button(nav,text=name,bg='#15171B',fg='#F5F5F5',borderwidth=0,anchor='w',padx=15,pady=10,command=lambda n=name:page(n)).pack(fill='x')
        page(self.extra_settings.get('last_category','General'))

    SHORTCUT_ACTIONS = {
        'Import Files': ('<Command-o>', 'add_files'),
        'Find Column': ('<Command-f>', 'focus_column_search'),
        'Duplicate Review': ('<Command-Shift-d>', 'duplicate_review'),
        'Name Cleanup': ('<Command-Shift-n>', 'name_cleanup_review'),
        'Task Queue': ('<Command-Shift-q>', 'queue_dialog'),
    }

    def _install_shortcuts(self):
        """Remapping never removes unrelated global bindings (including undo/cues)."""
        mapping = {}
        for action, (default, method) in self.SHORTCUT_ACTIONS.items():
            sequence = self.shortcut_settings.get(action, default)
            mapping[sequence] = method
        self._shortcut_dispatch_map = mapping
        registered = getattr(self, '_shortcut_registered_sequences', set())
        for sequence in mapping:
            if sequence in registered:
                continue
            def invoke(event, seq=sequence):
                if isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox)):
                    return None
                method = self._shortcut_dispatch_map.get(seq)
                if method:
                    getattr(self, method)()
                    return 'break'
                return None
            try:
                self.root.bind_all(sequence, invoke, add='+')
                registered.add(sequence)
            except tk.TclError:
                pass
        self._shortcut_registered_sequences = registered

    def focus_column_search(self):
        field = getattr(self, '_last_column_search', 'title')
        self.header_search(field if field in self.visible_columns else self.visible_columns[0])

    def _shortcut_settings_page(self, body):
        ttk.Label(body, text='Customize shortcuts using Tk notation, e.g. <Command-Shift-d>.').pack(anchor='w', pady=6)
        ttk.Label(body, text='Changes are saved immediately. Duplicate assignments are rejected.').pack(anchor='w', pady=6)
        for action, (default, _) in self.SHORTCUT_ACTIONS.items():
            line = ttk.Frame(body); line.pack(fill='x', pady=5)
            ttk.Label(line, text=action, width=22).pack(side='left')
            value = tk.StringVar(value=self.shortcut_settings.get(action, default))
            ttk.Entry(line, textvariable=value, width=28).pack(side='left', padx=6)
            def apply(a=action, v=value, d=default):
                sequence = v.get().strip() or d
                if not (sequence.startswith('<') and sequence.endswith('>')):
                    return messagebox.showerror('Shortcut', 'Use a valid <Command-key> sequence.')
                mapping = {k: self.shortcut_settings.get(k, spec[0]) for k, spec in self.SHORTCUT_ACTIONS.items()}
                mapping[a] = sequence
                if len(set(mapping.values())) != len(mapping):
                    return messagebox.showerror('Shortcut', 'That shortcut is already assigned.')
                self.shortcut_settings[a] = sequence
                self.save_preferences()
                self._install_shortcuts()
            ttk.Button(line, text='Apply', command=apply).pack(side='left')

    def _setting(self,key,value):
        self.extra_settings[key]=value;self.save_preferences()

    def restore_integrated_backup(self):
        folder=filedialog.askdirectory(title='Choose a DJ Tag Manager backup folder')
        if not folder:return
        manifest=Path(folder)/'manifest.json'
        try:
            data=json.loads(manifest.read_text())
            files=data['files']
            if not files or not all((Path(folder)/p).is_file() and Path(p).name==p for p in files):raise ValueError('Incomplete backup')
        except Exception as exc:return messagebox.showerror('Restore',str(exc))
        if not messagebox.askyesno('Restore',f'Restore {len(files)} app files from {data.get("created","unknown date")}?\nThe app will need to restart.'):return
        self.backup_now(quiet=True)
        for name in files:
            shutil.copy2(Path(folder)/name,self.data_dir/name)
        messagebox.showinfo('Restore','Backup restored. Close and reopen DJ Tag Manager to reload it.')

    def smart_filter_builder(self):
        win=tk.Toplevel(self.root);win.title('Smart Filter Builder');win.geometry('700x470')
        ttk.Label(win,text='Combine up to five conditions. Filters operate on displayed library fields.').pack(anchor='w',padx=15,pady=12)
        mode=tk.StringVar(value='AND');ttk.Combobox(win,textvariable=mode,values=['AND','OR'],state='readonly',width=9).pack(anchor='w',padx=15)
        conditions=[]
        fields=['title','artist','genre','composer','year','bitrate','filename','status']
        for _ in range(5):
            row=ttk.Frame(win);row.pack(fill='x',padx=15,pady=6)
            field=tk.StringVar(value='title');op=tk.StringVar(value='contains');value=tk.StringVar()
            ttk.Combobox(row,textvariable=field,values=fields,state='readonly',width=15).pack(side='left')
            ttk.Combobox(row,textvariable=op,values=['contains','equals','not contains','is empty'],state='readonly',width=16).pack(side='left',padx=8)
            ttk.Entry(row,textvariable=value).pack(side='left',fill='x',expand=True)
            conditions.append((field,op,value))
        def apply():
            rules=[(f.get(),o.get(),v.get()) for f,o,v in conditions if v.get().strip() or o.get()=='is empty']
            self.advanced_filter={'mode':mode.get(),'rules':rules}
            self._apply_advanced_filter();self.save_preferences();win.destroy()
        ttk.Button(win,text='Apply Filters',style='Accent.TButton',command=apply).pack(side='left',padx=15,pady=10)
        ttk.Button(win,text='Clear Filters',command=lambda:(setattr(self,'advanced_filter',{}),self._apply_advanced_filter(),self.save_preferences(),win.destroy())).pack(side='left')

    def _apply_advanced_filter(self):
        from app import display_value
        config=getattr(self,'advanced_filter',{})
        rules=config.get('rules',[])
        for path,row in self.rows.items():
            outcomes=[]
            for field,op,value in rules:
                actual=str(display_value(row,field)).casefold();needle=value.casefold()
                outcomes.append({'contains':lambda:needle in actual,'equals':lambda:needle==actual,
                                 'not contains':lambda:needle not in actual,'is empty':lambda:not actual.strip()}[op]())
            visible=(all(outcomes) if config.get('mode','AND')=='AND' else any(outcomes)) if outcomes else True
            visible=visible and self.matches_view(row,self.current_view)
            if self.tree.exists(path):
                if visible:self.tree.move(path,'','end')
                else:self.tree.detach(path)

    def genre_cleanup(self):
        """Show Genre Cleanup inside the main library workspace."""
        from genre_workspace import open_genre_workspace
        open_genre_workspace(self)

    def genre_restore_history(self):
        from app import write_any_tags,read_any_track
        win=tk.Toplevel(self.root);win.title('Genre Cleanup — Restore History');win.geometry('840x460')
        entries=[]
        tree=ttk.Treeview(win,columns=('date','count'),show='headings')
        tree.heading('date',text='Date');tree.heading('count',text='Files');tree.pack(fill='both',expand=True,padx=12,pady=12)
        for ident,created,action,payload in self.store.history_rows(500):
            if action!='genre_cleanup_written':continue
            try:files=json.loads(payload)['files']
            except Exception:continue
            entries.append((ident,files));tree.insert('','end',iid=str(len(entries)-1),values=(created,len(files)))
        def restore():
            if not tree.selection():return
            files=entries[int(tree.selection()[0])][1]
            if not messagebox.askyesno('Restore',f'Restore original Genre and Composer on {len(files)} tracks?',parent=win):return
            success=0
            for item in files:
                path=item['path']
                if not Path(path).is_file():continue
                try:
                    from metadata_safety import safe_write
                    safe_write(path, item['before'], {}, write_any_tags, read_any_track,
                               self.data_dir / 'metadata_recovery',
                               expected=self.rows.get(path, {}).get('disk_fingerprint'))
                    self.rows[path].update(read_any_track(path));self.refresh(path);success+=1
                except Exception:pass
            self.store.history('genre_cleanup_restored',{'original_action':entries[int(tree.selection()[0])][0],'restored':success})
            self.persist_library();messagebox.showinfo('Restored',f'{success} tracks restored.',parent=win)
        ttk.Button(win,text='Restore Selected Action',command=restore).pack(pady=8)

    def name_cleanup_review(self):
        """Review, edit, dismiss, or stage name suggestions without implicit writes."""
        from cleanup_engine import name_candidates
        win=tk.Toplevel(self.root);win.title('Name Cleanup — Potential Fixes');win.geometry('1120x650')
        ttk.Label(win,text='Name Cleanup · Title, Artist and Potential Fixes',font=('Helvetica',18,'bold')).pack(anchor='w',padx=16,pady=10)
        dismissed=set(self.extra_settings.get('dismissed_name_fixes',[]))
        suggestions=[]
        for item in name_candidates(self.rows, dismissed):
            suggestions.append((item['id'],item['path'],item['field'],item['before'],item['after'],item['confidence']))
        top=ttk.Frame(win,padding=10);top.pack(fill='x')
        ttk.Button(top,text='Scan External Folder…',command=lambda:self.name_external_scan(win)).pack(side='right',padx=5)
        search=tk.StringVar();ttk.Entry(top,textvariable=search).pack(side='left',fill='x',expand=True)
        field_filter=tk.StringVar(value='All');ttk.Combobox(top,textvariable=field_filter,values=['All','title','artist'],state='readonly',width=12).pack(side='left',padx=8)
        holder=ttk.Frame(win);holder.pack(fill='both',expand=True,padx=10)
        tree=ttk.Treeview(holder,columns=('field','before','after','confidence','file'),show='headings',selectmode='extended')
        for col,width in [('field',85),('before',240),('after',240),('confidence',95),('file',320)]:
            tree.heading(col,text=col.title(),command=lambda c=col:sort_by(c))
            tree.column(col,width=width)
        tree.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(holder,command=tree.yview);scrollbar.pack(side='right',fill='y');tree.configure(yscrollcommand=scrollbar.set)
        tree.tag_configure('high',foreground='#66D8A2');tree.tag_configure('medium',foreground='#FFB95B');tree.tag_configure('low',foreground='#FF7777')
        edits={};reverse=False;order=list(range(len(suggestions)))
        def redraw(*_):
            tree.delete(*tree.get_children())
            for i in order:
                ident,path,field,before,after,score=suggestions[i]
                if ident in dismissed:continue
                if field_filter.get()!='All' and field!=field_filter.get():continue
                shown=edits.get(i,after)
                if search.get().casefold() not in (path+' '+field+' '+before+' '+shown).casefold():continue
                tag='high' if score>=70 else 'medium' if score>=40 else 'low'
                tree.insert('','end',iid=str(i),values=(field,before,shown,f'{score}%',Path(path).name),tags=(tag,))
        def sort_by(col):
            nonlocal reverse
            cols={'field':2,'before':3,'after':4,'confidence':5,'file':1}
            order.sort(key=lambda i:str(suggestions[i][cols[col]]).casefold(),reverse=reverse)
            reverse=not reverse;redraw()
        search.trace_add('write',redraw);field_filter.trace_add('write',redraw)
        redraw()
        controls=ttk.Frame(win,padding=10);controls.pack(fill='x')
        def selected():return [int(i) for i in tree.selection()]
        def edit():
            chosen=selected()
            if len(chosen)!=1:return messagebox.showinfo('Name Cleanup','Select one suggestion to edit.',parent=win)
            i=chosen[0];current=edits.get(i,suggestions[i][4])
            dialog=tk.Toplevel(win);dialog.title('Edit Proposed Value');dialog.geometry('540x150')
            value=tk.StringVar(value=current)
            ttk.Entry(dialog,textvariable=value).pack(fill='x',padx=15,pady=20)
            ttk.Button(dialog,text='Apply to Proposal',command=lambda:(edits.__setitem__(i,value.get()),redraw(),dialog.destroy())).pack()
        def dismiss():
            for i in selected():dismissed.add(suggestions[i][0])
            self.extra_settings['dismissed_name_fixes']=sorted(dismissed)
            self.save_preferences();redraw()
        def stage():
            chosen=selected()
            if not chosen:return
            self.push_undo()
            for i in chosen:
                ident,path,field,before,after,score=suggestions[i]
                value=edits.get(i,after).strip()
                if not value:continue
                self.rows[path].setdefault('pending_tags',{})[field]=value
                self.rows[path]['status']=f'Name cleanup {score}% — pending save'
                self.refresh(path)
            self.store.history('name_cleanup_staged',{'count':len(chosen)})
            win.destroy()
            messagebox.showinfo('Staged',f'{len(chosen)} suggestions staged. Use Save Changes to write actual music files.')
        ttk.Button(controls,text='Edit Proposal',command=edit).pack(side='left',padx=4)
        ttk.Button(controls,text='Dismiss Selected',command=dismiss).pack(side='left',padx=4)
        ttk.Button(controls,text='Stage Selected',style='Accent.TButton',command=stage).pack(side='left',padx=4)
        ttk.Button(controls,text='Stage All Visible',command=lambda:(tree.selection_set(tree.get_children()),stage())).pack(side='left',padx=4)
        ttk.Label(controls,text='Green ≥70% · Orange 40–69% · Red <40% · No automatic writes',style='Muted.TLabel').pack(side='right')


    def name_external_scan(self, parent=None):
        """Explicit external import with incremental scan and review-only suggestions."""
        from cleanup_engine import discover_audio_files, incremental_name_scan, name_candidates
        from app import read_any_track
        folder=filedialog.askdirectory(title='Choose a folder to scan for name suggestions',parent=parent or self.root)
        if not folder:return
        dialog=tk.Toplevel(self.root);dialog.title('Name Cleanup — External Folder Scan');dialog.geometry('940x620')
        header=ttk.Frame(dialog,padding=12);header.pack(fill='x')
        ttk.Label(header,text='External files · Review before importing',font=('Helvetica',16,'bold')).pack(anchor='w')
        recursive=tk.BooleanVar(value=True);force=tk.BooleanVar(value=False)
        ttk.Checkbutton(header,text='Include subfolders',variable=recursive).pack(side='left',padx=5)
        ttk.Checkbutton(header,text='Force rescan unchanged files',variable=force).pack(side='left',padx=5)
        info=ttk.Label(dialog,text='Choose Scan. No audio files will be changed.',padding=10)
        info.pack(anchor='w')
        tree=ttk.Treeview(dialog,columns=('field','before','after','confidence','file'),show='headings',selectmode='extended')
        for col,width in [('field',85),('before',205),('after',205),('confidence',95),('file',285)]:
            tree.heading(col,text=col.title());tree.column(col,width=width)
        tree.pack(fill='both',expand=True,padx=12,pady=8)
        proposals=[];scanned=[]
        def scan():
            nonlocal proposals,scanned
            try:
                files=discover_audio_files(folder,recursive.get())
                cache=self.extra_settings.get('name_scan_cache',{})
                rows,new_cache,failures=incremental_name_scan(files,cache,read_any_track,force.get())
                # Keep cache for successful scans only. Do not modify the library.
                self.extra_settings['name_scan_cache']=new_cache
                self.save_preferences()
                scanned=list(rows)
                proposals=name_candidates(rows,set(self.extra_settings.get('dismissed_name_fixes',[])))
                tree.delete(*tree.get_children())
                for index,item in enumerate(proposals):
                    tree.insert('','end',iid=str(index),values=(item['field'],item['before'],item['after'],f"{item['confidence']}%",Path(item['path']).name))
                info.config(text=f'{len(files)} audio files found · {len(rows)} new/changed scanned · {len(proposals)} suggestions · {len(failures)} unreadable · {len(files)-len(rows)-len(failures)} unchanged skipped')
            except Exception as exc:messagebox.showerror('Scan failed',str(exc),parent=dialog)
        controls=ttk.Frame(dialog,padding=12);controls.pack(fill='x')
        ttk.Button(controls,text='Scan',command=scan).pack(side='left',padx=4)
        def import_selected():
            paths=list(dict.fromkeys(proposals[int(i)]['path'] for i in tree.selection()))
            if not paths:return messagebox.showinfo('Import','Select suggestions first.',parent=dialog)
            if not messagebox.askyesno('Import files',f'Import {len(paths)} source files into the library for review?\n\nThis will not change audio metadata.',parent=dialog):return
            self.add_paths(paths)
            messagebox.showinfo('Imported','Files added to the library. Open Name Cleanup again to review and stage proposals.',parent=dialog)
            dialog.destroy()
        ttk.Button(controls,text='Import Selected for Review',command=import_selected).pack(side='left',padx=4)
        ttk.Label(controls,text='No automatic writing · Unchanged files skipped unless forced',style='Muted.TLabel').pack(side='right')
