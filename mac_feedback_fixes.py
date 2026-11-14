"""Mac integration feedback fixes: readable track access, observable jobs, contextual actions.

No metadata writes are initiated by this module. UI-only changes, plus column state
normalization. Tk widgets must only be touched on the main thread.
"""
import tkinter as tk
from tkinter import ttk, messagebox


def normalized_visible_columns(visible, all_fields, mandatory=('title', 'artist')):
    """Preserve order, deduplicate and make essential track identity accessible."""
    available = set(all_fields)
    result = [key for key in dict.fromkeys(visible) if key in available]
    for key in reversed(mandatory):
        if key in available and key not in result:
            result.insert(0, key)
    return result


class MacFeedbackFixes:
    def install_mac_feedback_fixes(self):
        self.visible_columns = normalized_visible_columns(self.visible_columns, self.column_labels_for_feedback())
        self.tree.configure(displaycolumns=tuple(self.visible_columns))
        self.save_column_layout()
        self.tree.bind('<Button-2>', self.feedback_context_menu)
        self.tree.bind('<Button-3>', self.feedback_context_menu)
        self.tree.bind('<Control-Button-1>', self.feedback_context_menu)
        self._feedback_search = None
        self.root.bind('<Button-1>', self._feedback_outside_click, add='+')
        self._feedback_job = tk.StringVar(value='No active task')
        self._feedback_bar = ttk.Frame(self.root, padding=(12, 5))
        ttk.Label(self._feedback_bar, textvariable=self._feedback_job).pack(side='left', padx=8)
        self._feedback_progress = ttk.Progressbar(self._feedback_bar, maximum=1, length=230, mode='determinate')
        self._feedback_progress.pack(side='left', padx=8)
        ttk.Button(self._feedback_bar, text='Task Details / Pause / Cancel', command=self.queue_dialog).pack(side='right', padx=8)
        self._feedback_bar.pack(fill='x', before=self.status)
        self.root.after(400, self._feedback_tick)
        # Avoid the native tk.Button appearance that produces a white rectangle on macOS.
        self.help_button.configure(bg='#30353E', fg='#FACC15', activebackground='#3A414B',
                                   activeforeground='#FACC15', highlightthickness=0,
                                   highlightbackground='#30353E', bd=0)

    def column_labels_for_feedback(self):
        from app import COLUMN_LABELS
        return COLUMN_LABELS

    def feedback_context_menu(self, event):
        region = self.tree.identify_region(event.x, event.y)
        if region == 'heading':
            self.column_dropdown(event.x_root, event.y_root)
            return 'break'
        if region not in ('cell', 'tree'):
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        if item not in self.tree.selection():
            self.tree.selection_set(item)
        menu = tk.Menu(self.root, tearoff=False, bg='#242830', fg='#F3F5F8',
                       activebackground='#3A414B', activeforeground='#FACC15')
        menu.add_command(label='Play Selected', command=lambda: self.play_track(self.selected()[0]))
        menu.add_separator()
        menu.add_command(label='Edit Metadata…', command=self.edit_all_tags)
        menu.add_command(label='Find Tags & Art…', command=self.lookup)
        menu.add_command(label='Analyze BPM', command=self.analyze)
        menu.add_separator()
        menu.add_command(label='Name Cleanup…', command=self.name_cleanup_review)
        menu.add_command(label='Genre Cleanup…', command=self.genre_cleanup)
        menu.add_command(label='Duplicate Review…', command=self.duplicate_review)
        menu.add_separator()
        menu.add_command(label='Show in Finder', command=self.reveal_selected)
        menu.add_command(label='Customize Columns…', command=self.choose_columns)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
            self.root.after_idle(menu.destroy)
        return 'break'

    def column_dropdown(self, x=None, y=None):
        """Visible eye marker follows actual displaycolumns, not stale checkbox state."""
        old = getattr(self, '_column_popup', None)
        if old is not None and old.winfo_exists():
            old.destroy()
        from app import COLUMN_LABELS
        pop = tk.Toplevel(self.root)
        self._column_popup = pop
        pop.overrideredirect(True)
        pop.configure(bg='#343A44')
        pop.geometry(f'+{x or self.tree.winfo_rootx()}+{y or self.tree.winfo_rooty()}')
        body = tk.Frame(pop, bg='#242830', padx=10, pady=10)
        body.pack(padx=1, pady=1)
        tk.Label(body, text='COLUMNS  ·  yellow eye = visible', bg='#242830', fg='#FACC15',
                 font=('Helvetica', 12, 'bold')).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 8))
        controls = {}
        def refresh():
            for field, button in controls.items():
                visible = field in self.visible_columns
                button.configure(text=('◉  ' if visible else '     ') + COLUMN_LABELS[field],
                                 fg='#FACC15' if visible else '#E5E7EB')
        def toggle(field):
            # Title and Artist are required to keep the library navigable.
            if field in ('title', 'artist') and field in self.visible_columns:
                messagebox.showinfo('Columns', 'Title and Artist remain visible so you can identify songs.', parent=pop)
                return
            self.toggle_column(field)
            refresh()
        for i, field in enumerate(COLUMN_LABELS):
            button = tk.Button(body, anchor='w', bg='#242830', activebackground='#30353E',
                               activeforeground='#FACC15', relief='flat', bd=0,
                               font=('Helvetica', 12), padx=8, pady=5,
                               command=lambda f=field: toggle(f))
            button.grid(row=1 + i % 14, column=i // 14, sticky='ew', padx=3)
            controls[field] = button
        refresh()
        tk.Button(body, text='Done', command=pop.destroy, bg='#30353E', fg='#F3F5F8',
                  relief='flat').grid(row=16, column=0, columnspan=2, sticky='ew', pady=(10, 0))
        pop.bind('<Escape>', lambda _e: pop.destroy())
        pop.bind('<FocusOut>', lambda _e: self.root.after(100, lambda: pop.destroy() if pop.winfo_exists() and self.root.focus_get() not in controls.values() else None))
        pop.lift()
        pop.focus_set()

    def header_search(self, field):
        """Keep filter value but dismiss the transient editor on blur."""
        from app import COLORS
        self.close_feedback_search()
        if field not in self.visible_columns:
            return
        self.root.update_idletasks()
        x = sum(self.tree.column(k, 'width') for k in self.visible_columns[:self.visible_columns.index(field)])
        width = self.tree.column(field, 'width')
        var = tk.StringVar(value=self.filters.get(field, ''))
        entry = ttk.Entry(self.tree, textvariable=var)
        self._feedback_search = entry
        self._inline_header_entry = entry
        entry.place(x=x+2, y=2, width=max(75, width-4), height=29)
        def changed(*_):
            value = var.get().strip()
            if value: self.filters[field] = value
            else: self.filters.pop(field, None)
            self.apply_filters()
        var.trace_add('write', changed)
        entry.bind('<Escape>', lambda _e: (self.close_feedback_search(), 'break')[-1])
        entry.bind('<Return>', lambda _e: (self.close_feedback_search(), 'break')[-1])
        entry.bind('<FocusOut>', lambda _e: self.root.after_idle(self.close_feedback_search))
        entry.focus_set()
        entry.selection_range(0, 'end')

    def close_feedback_search(self):
        entry = getattr(self, '_feedback_search', None)
        self._feedback_search = None
        if entry is not None:
            try:
                if entry.winfo_exists(): entry.destroy()
            except tk.TclError: pass

    def _feedback_outside_click(self, event):
        entry = getattr(self, '_feedback_search', None)
        if entry is not None and event.widget is not entry:
            self.close_feedback_search()

    def run_job(self, kind, paths=None):
        paths = self.selected() if paths is None else paths
        if not paths:
            messagebox.showinfo('DJ Tag Manager', 'Select one or more songs first.\n\nTip: Title and Artist are always visible.')
            return
        if kind not in ('lookup', 'analyze', 'lookup_analyze'):
            messagebox.showwarning('DJ Tag Manager', 'Unsupported task type.')
            return
        job_id = self.queue_engine.add(kind, paths)
        self._feedback_job.set(f'Task #{job_id} queued · {len(paths)} tracks · Open Task Details for progress')
        self._feedback_progress.configure(maximum=len(paths), value=0)
        self.status.configure(text=f'Task #{job_id} queued: {len(paths)} tracks. Open Task Details to inspect results.')
        self._feedback_bar.pack(fill='x', before=self.status)
        # Immediate confirmation rather than silent background work.
        messagebox.showinfo('Metadata task started',
            f'Task #{job_id} has been queued for {len(paths)} track(s).\n\n'
            'The progress strip shows its status. Use Task Details to pause, cancel, or inspect failures.')

    def _feedback_tick(self):
        if not self.root.winfo_exists():
            return
        try:
            jobs = self.queue_engine.snapshot(30)
            active = next((j for j in jobs if j['state'] == 'running'), None)
            if active is None:
                active = next((j for j in jobs if j['state'] == 'waiting'), None)
            if active:
                self._feedback_bar.pack(fill='x', before=self.status)
                self._feedback_progress.configure(maximum=max(1, active['total']), value=active['cursor'])
                self._feedback_job.set(f"Task #{active['id']} · {active['kind']} · {active['cursor']}/{active['total']} · "
                                       f"{active['successes']} processed · {len(active['errors'])} errors"
                                       + (' · Paused' if self.queue_engine.paused else ''))
            elif jobs:
                recent = jobs[0]
                self._feedback_progress.configure(maximum=max(1, recent['total']), value=recent['cursor'])
                self._feedback_job.set(f"Last task #{recent['id']}: {recent['state']} · "
                                       f"{recent['cursor']}/{recent['total']} · {len(recent['errors'])} errors")
        except (tk.TclError, AttributeError, OSError):
            pass
        self.root.after(650, self._feedback_tick)
