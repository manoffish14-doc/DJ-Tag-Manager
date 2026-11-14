"""Additional user-facing workflows. Imported by app.py to avoid altering v2."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from library_features import duplicate_groups, preferred_copy, archive_files, restore_archive, name_suggestions, LibraryStore


class AdvancedTools:
    def setup_advanced(self):
        self.store = LibraryStore(self.data_dir / 'v3_combined.sqlite3')
        self.root.bind_all('<Command-Shift-d>', lambda e: self.duplicate_review(), add='+')
        self.root.bind_all('<Command-Shift-n>', lambda e: self.name_cleanup_review(), add='+')
        self.root.bind_all('<KeyPress-space>', self._space_player, add='+')
        for n in range(1, 9):
            self.root.bind_all(f'<KeyPress-{n}>', lambda e, slot=n: self.jump_or_set_cue(slot), add='+')
        self.add_advanced_sidebar()

    def _space_player(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text, ttk.Entry, tk.Listbox)):
            return
        self.toggle_playback()
        return 'break'

    def add_advanced_sidebar(self):
        tk.Label(self.sidebar, text='ADVANCED TOOLS', bg='#15171B', fg='#FACC15',
                 font=('Helvetica', 11, 'bold')).pack(anchor='w', padx=14, pady=(14, 5))
        for label, fn in [('Review Duplicates', self.duplicate_review),
                          ('Name Cleanup', self.name_cleanup_review),
                          ('Hot Cues (App)', self.hot_cue_editor),
                          ('Restore Archive', self.restore_archive_dialog),
                          ('Cleanup History', self.cleanup_history)]:
            tk.Button(self.sidebar, text=label, anchor='w', bg='#15171B', fg='#F5F5F5',
                      borderwidth=0, padx=14, pady=6, command=fn).pack(fill='x')

    def duplicate_review(self, similar=False):
        """Sortable duplicate review, persistent Keep/Reviewed and archive-only commits."""
        from cleanup_engine import duplicate_clusters, similar_duplicate_clusters, group_id, best_copy, archive_plan
        groups = similar_duplicate_clusters(self.rows) if similar else duplicate_clusters(self.rows)
        win = tk.Toplevel(self.root); win.title('Duplicate Finder — Review & Archive'); win.geometry('1220x730')
        top = ttk.Frame(win, padding=12); top.pack(fill='x')
        ttk.Label(top, text=('Similar Title Review' if similar else 'Duplicate Finder') + ' · Clean / Explicit / Unknown kept separate',
                  font=('Helvetica', 17, 'bold')).pack(anchor='w')
        ttk.Label(top, text='Only reviewed groups may archive tracks. At least one Keep is required per group. No deletion.').pack(anchor='w')
        ttk.Button(top, text='Switch to ' + ('Exact Matches' if similar else 'Similar Titles'), command=lambda:(win.destroy(), self.duplicate_review(not similar))).pack(anchor='w',pady=3)
        prefer_plays = tk.BooleanVar(value=bool(self.extra_settings.get('duplicate_prefer_plays', True)))
        ttk.Checkbutton(top, text='Use play count after bitrate for Keep recommendation',
                        variable=prefer_plays).pack(anchor='w', pady=4)
        holder = ttk.Frame(win, padding=(12, 0, 12, 0)); holder.pack(fill='both', expand=True)
        columns = ('group', 'keep', 'reviewed', 'artist', 'title', 'version', 'bitrate', 'plays', 'file', 'folder')
        tree = ttk.Treeview(holder, columns=columns, show='headings', selectmode='extended')
        widths = {'group':75,'keep':65,'reviewed':80,'artist':150,'title':210,'version':90,
                  'bitrate':75,'plays':65,'file':210,'folder':260}
        entries = []
        decisions = {}
        for idx, group in enumerate(groups, 1):
            gid = group_id(group); key = 'duplicate_review:' + gid
            with self.store.connect() as db:
                saved = db.execute('SELECT value FROM preferences WHERE name=?', (key,)).fetchone()
            try: saved = json.loads(saved[0]) if saved else {}
            except (ValueError, TypeError): saved = {}
            keeps = saved.get('keeps')
            if isinstance(keeps, dict): keeps = [p for p, flag in keeps.items() if flag]
            if keeps is None: keeps = [best_copy(group, self.rows, prefer_plays.get())]
            decisions[gid] = {'reviewed': bool(saved.get('reviewed', False)), 'keeps': set(keeps)}
            for path in group:
                row = self.rows[path]
                from cleanup_engine import version_kind, play_count
                entries.append((str(len(entries)), idx, gid, path, row, version_kind(row), play_count(row)))
        def persist(gid):
            payload = {'reviewed': decisions[gid]['reviewed'], 'keeps': sorted(decisions[gid]['keeps'])}
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO preferences(name,value) VALUES (?,?)',
                           ('duplicate_review:' + gid, json.dumps(payload)))
        def values(entry):
            _, index, gid, path, row, version, plays = entry
            state = decisions[gid]
            return (index, '✓' if path in state['keeps'] else '', '✓' if state['reviewed'] else '',
                    row.get('artist',''), row.get('title',''), version, row.get('bitrate',''),
                    plays, Path(path).name, str(Path(path).parent))
        for col in columns:
            tree.heading(col, text=col.title(), command=lambda c=col: sort(c))
            tree.column(col, width=widths[col], minwidth=45, stretch=col in ('title','file','folder'))
        scroll = ttk.Scrollbar(holder, orient='vertical', command=tree.yview)
        xscroll = ttk.Scrollbar(holder, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=scroll.set, xscrollcommand=xscroll.set)
        scroll.pack(side='right', fill='y'); xscroll.pack(side='bottom', fill='x')
        tree.pack(side='left', fill='both', expand=True)
        order = list(entries); sort_reverse = False
        def redraw():
            selected = set(tree.selection())
            tree.delete(*tree.get_children())
            for entry in order: tree.insert('', 'end', iid=entry[0], values=values(entry))
            for iid in selected:
                if tree.exists(iid): tree.selection_add(iid)
        def sort(col):
            nonlocal sort_reverse
            i = columns.index(col)
            def key(entry):
                v = values(entry)[i]
                if col in ('bitrate','plays','group'):
                    import re
                    match = re.search(r'\d+', str(v))
                    return int(match.group()) if match else 0
                return str(v).casefold()
            order.sort(key=key, reverse=sort_reverse); sort_reverse = not sort_reverse; redraw()
        def chosen(): return [next(e for e in entries if e[0] == iid) for iid in tree.selection()]
        def toggle_keep():
            for _, _, gid, path, _, _, _ in chosen():
                keep = decisions[gid]['keeps']
                if path in keep: keep.remove(path)
                else: keep.add(path)
                decisions[gid]['reviewed'] = False
                persist(gid)
            redraw()
        def mark_reviewed():
            for _, _, gid, _, _, _, _ in chosen():
                if not decisions[gid]['keeps']:
                    return messagebox.showwarning('Keep required', 'Choose at least one Keep in each group.', parent=win)
                decisions[gid]['reviewed'] = True; persist(gid)
            redraw()
        def reset_recommendations():
            self.extra_settings['duplicate_prefer_plays'] = prefer_plays.get()
            self.save_preferences()
            for group in groups:
                gid = group_id(group)
                if not decisions[gid]['reviewed']:
                    decisions[gid]['keeps'] = {best_copy(group, self.rows, prefer_plays.get())}
                    persist(gid)
            redraw()
        def archive():
            if similar and not messagebox.askyesno('Similar-title safety', 'These are approximate matches, not verified duplicates. Have you listened to every track marked for archiving?', parent=win): return
            try: targets = archive_plan(groups, decisions)
            except ValueError as exc: return messagebox.showwarning('Keep required', str(exc), parent=win)
            if not targets: return messagebox.showinfo('No tracks selected', 'Review groups and uncheck Keep for the tracks to archive.', parent=win)
            folder = filedialog.askdirectory(title='Select existing archive folder', parent=win)
            if not folder: return
            if not messagebox.askyesno('Confirm archive', f'Archive {len(targets)} tracks to\n{folder}?\n\nNo files will be deleted.', parent=win): return
            try: manifest, filename = archive_files(targets, folder, self.rows)
            except Exception as exc: return messagebox.showerror('Archive blocked', str(exc), parent=win)
            for path in targets:
                if self.tree.exists(path): self.tree.delete(path)
                self.rows.pop(path, None)
            self.store.history('archive', {'manifest': str(filename), 'moves': manifest['moves']})
            self.persist_library(); self.update_sidebar_counts(); win.destroy()
            messagebox.showinfo('Archive completed', f'{len(targets)} tracks archived.\nRestore manifest: {filename}')
        buttons = ttk.Frame(win, padding=12); buttons.pack(fill='x')
        for label, callback in [('Toggle Keep',toggle_keep), ('Mark Group Reviewed',mark_reviewed),
                                ('Recalculate Unreviewed',reset_recommendations),
                                ('Restore Archive…',self.restore_archive_dialog)]:
            ttk.Button(buttons, text=label, command=callback).pack(side='left', padx=4)
        ttk.Button(buttons, text='Archive Reviewed', command=archive, style='Accent.TButton').pack(side='right')
        ttk.Label(win, text=f'{len(groups)} groups · {len(entries)} matching tracks · Select rows to change Keep / Reviewed',
                  style='Muted.TLabel').pack(anchor='w', padx=15, pady=(0,8))
        redraw()

    def restore_archive_dialog(self):
        filename = filedialog.askopenfilename(title='Choose DJ Tag Manager archive manifest',
            filetypes=[('JSON', '*.json')])
        if not filename: return
        if not messagebox.askyesno('Restore archive', 'Restore archived tracks to their original locations? Existing files will not be overwritten.'):
            return
        try:
            data = json.loads(Path(filename).read_text(encoding='utf-8'))
            count = restore_archive(filename)
            self.add_paths([m['from'] for m in data['moves']])
            self.store.history('restore_archive', {'manifest': filename, 'count': count})
            messagebox.showinfo('Restored', f'Restored {count} files.')
        except Exception as exc:
            messagebox.showerror('Restore failed', str(exc))

    def name_cleanup_review(self):
        suggestions = []
        for path, row in self.rows.items():
            for field, (replacement, score) in name_suggestions(row).items():
                suggestions.append((path, field, row.get(field, ''), replacement, score))
        win = tk.Toplevel(self.root)
        win.title('Name Cleanup — Review Suggestions')
        win.geometry('1040x620')
        ttk.Label(win, text='Select suggestions to stage. No music file is written until Save Changes.').pack(anchor='w', padx=15, pady=10)
        holder = ttk.Frame(win)
        holder.pack(fill='both', expand=True, padx=12)
        tree = ttk.Treeview(holder, columns=('field','before','after','confidence','file'), show='headings', selectmode='extended')
        for col, width in [('field',80),('before',240),('after',240),('confidence',90),('file',300)]:
            tree.heading(col, text=col.title())
            tree.column(col, width=width)
        for i, (path, field, before, after, score) in enumerate(suggestions):
            tree.insert('', 'end', iid=str(i), values=(field, before, after, str(score)+'%', Path(path).name))
        tree.pack(fill='both', expand=True)
        def stage():
            chosen = list(tree.selection())
            if not chosen: return
            self.push_undo()
            for item in chosen:
                path, field, before, after, score = suggestions[int(item)]
                self.rows[path].setdefault('pending_tags', {})[field] = after
                self.rows[path]['status'] = f'Name cleanup {score}% — pending save'
                self.refresh(path)
            self.store.history('name_suggestions_staged', {'count':len(chosen)})
            win.destroy()
            messagebox.showinfo('Staged', f'{len(chosen)} changes staged. Review and click Save Changes to write music files.')
        ttk.Button(win, text='Stage Selected Suggestions', command=stage, style='Accent.TButton').pack(pady=10)

    def hot_cue_editor(self):
        path = self.player_path or (self.selected()[0] if self.selected() else None)
        if not path:
            return messagebox.showinfo('Hot Cues', 'Load or select a song first.')
        win = tk.Toplevel(self.root)
        win.title('Hot Cues — App Library (not Serato)')
        win.geometry('540x510')
        ttk.Label(win, text='These cues are stored in DJ Tag Manager only. Serato data is untouched.').pack(padx=12, pady=12)
        container = ttk.Frame(win)
        container.pack(fill='both', expand=True, padx=15)
        def redraw():
            for child in container.winfo_children(): child.destroy()
            existing = {c['slot']:c for c in self.store.cues(path)}
            for slot in range(1, 9):
                cue = existing.get(slot)
                line = ttk.Frame(container)
                line.pack(fill='x', pady=3)
                ttk.Label(line, text=f'{slot}', width=3).pack(side='left')
                seconds = tk.StringVar(value=f"{cue['seconds']:.2f}" if cue else '0.00')
                label = tk.StringVar(value=cue['label'] if cue else '')
                ttk.Entry(line, textvariable=seconds, width=10).pack(side='left', padx=4)
                ttk.Entry(line, textvariable=label, width=22).pack(side='left', padx=4)
                def save(s=slot, t=seconds, l=label):
                    try: self.store.save_cue(path, s, float(t.get()), l.get())
                    except Exception as exc: return messagebox.showerror('Invalid cue', str(exc), parent=win)
                    redraw()
                ttk.Button(line, text='Save', command=save).pack(side='left', padx=3)
                ttk.Button(line, text='Clear', command=lambda s=slot: (self.store.clear_cue(path,s),redraw())).pack(side='left')
        redraw()

    def jump_or_set_cue(self, slot):
        if not self.player_path or not Path(self.player_path).is_file(): return
        cues = {c['slot']:c for c in self.store.cues(self.player_path)}
        if slot in cues:
            self.waveform_controller.seek(cues[slot]['seconds'])
        else:
            self.store.save_cue(self.player_path,slot,self.waveform_controller.position,f'Cue {slot}')
            self.waveform_controller.wave.cues=self.store.cues(self.player_path)
            self.waveform_controller.wave.draw()
            self.status.configure(text=f'Cue {slot} set at {self.waveform_controller.position:.2f}s')

    def cleanup_history(self):
        win = tk.Toplevel(self.root)
        win.title('Cleanup History')
        win.geometry('850x450')
        txt = tk.Text(win, bg='#141922', fg='#F5F5F5')
        txt.pack(fill='both', expand=True)
        for id_, created, action, payload in self.store.history_rows():
            txt.insert('end', f'{created} | {action}\n{payload}\n\n')
        txt.configure(state='disabled')
