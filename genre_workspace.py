"""Lexicon-style vertical genre families with immediate, recoverable bulk writes."""
from collections import defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import re

DEFAULT_GROUPS = ('Hip Hop', 'R&B', 'Pop', 'Classic Rock', 'Rock', 'African', 'Other')
SUGGESTED = {
    'Hip Hop': ('Hip-Hop', 'Rap', 'Trap', 'Boom Bap', 'Drill', 'Old School Hip Hop'),
    'R&B': ('R&B', 'Contemporary R&B', 'Neo Soul', 'Soul', 'New Jack Swing'),
    'Pop': ('Pop', 'Dance Pop', 'Synth Pop', 'Electropop'),
    'Classic Rock': ('Classic Rock', 'Southern Rock', 'Psychedelic Rock'),
    'Rock': ('Alternative Rock', 'Hard Rock', 'Indie Rock', 'Punk Rock'),
    'African': ('Afrobeats', 'Afro House', 'Amapiano', 'Highlife'),
    'Other': ('Dancehall', 'Reggae', 'Latin', 'Country'),
}


def canonical_genre(name):
    """Conservative duplicate detection: case, whitespace and punctuation insensitive."""
    return re.sub(r"[^a-z0-9]+", "", str(name).casefold())

def is_duplicate_genre(name, names):
    return any(canonical_genre(name) == canonical_genre(existing) for existing in names)

def inventory(rows, custom=()):
    found = defaultdict(list)
    for path, row in rows.items():
        genre = str(row.get('genre') or '').strip()
        if genre:
            found[genre].append(path)
    for name in (*DEFAULT_GROUPS, *custom):
        found.setdefault(name, [])
    return dict(found)


def plan_genre_writes(rows, assignments):
    """Pure plan: {subgenre: parent} -> {path: metadata}, preserving the original genre."""
    planned = {}
    for path, row in rows.items():
        original = str(row.get('genre') or '').strip()
        parent = assignments.get(original)
        if parent and original != parent:
            planned[path] = {'genre': parent, 'composer': original}
    return planned


def open_genre_workspace(app):
    from cleanup_engine import genre_group
    from app import read_any_track, write_any_tags
    from metadata_safety import safe_write

    existing = getattr(app, '_genre_workspace', None)
    if existing is not None and existing.winfo_exists():
        return
    table = app._library_table_frame
    # Give Genre Cleanup the entire main workspace. Preserve widget instances
    # and playback state so returning to Library is immediate.
    hidden = []
    for widget in (app.main_toolbar, app.drop_label, app.details):
        if widget.winfo_manager() == 'pack':
            hidden.append((widget, widget.pack_info()))
            widget.pack_forget()
    prior_collapsed = app.player_collapsed
    app.set_player_collapsed(True)
    app.player_panel.pack_forget()
    prior_feedback_visible = getattr(app, "_feedback_bar", None) is not None and bool(app._feedback_bar.winfo_manager())
    if prior_feedback_visible:
        app._feedback_bar.pack_forget()
    prior_status_visible = bool(app.status.winfo_manager())
    if prior_status_visible:
        app.status.pack_forget()
    table.pack_forget()
    host = ttk.Frame(app.content)
    host.pack(side='left', fill='both', expand=True)
    app._genre_workspace = host
    organization = app.extra_settings.setdefault('genre_organization', {})
    custom_groups = app.extra_settings.setdefault('genre_custom_groups', [])
    custom_genres = app.extra_settings.setdefault('genre_custom_genres', [])
    # Seed the familiar families without changing any track metadata.
    for group, names in SUGGESTED.items():
        for name in names:
            organization.setdefault(name, group)
    query = tk.StringVar()
    status = tk.StringVar(value='Select a genre family or individual subgenres, then Save Changes.')
    chosen = set()  # (parent, subgenre); selection is independent of file writes
    family_widgets = {}
    pending = tk.StringVar(value="")
    drag = {"source": None, "start": None, "moved": False, "target": None}
    dark, panel, fg, yellow = '#15171B', '#22252B', '#F2F3F5', '#FACC15'

    def close():
        host.destroy()
        app._genre_workspace = None
        table.pack(side='left', fill='both', expand=True)
        for widget, pack_options in hidden:
            widget.pack(**pack_options)
        if not app.player_panel.winfo_manager():
            app.player_panel.pack(side='bottom', fill='x', padx=12, pady=(0, 5))
        app.set_player_collapsed(prior_collapsed)
        if prior_feedback_visible:
            app._feedback_bar.pack(fill="x", before=app.player_panel)
        if prior_status_visible:
            app.status.pack(fill="x", before=app.player_panel)

    header = ttk.Frame(host, padding=(12, 10))
    header.pack(fill='x')
    ttk.Label(header, text='Genre Cleanup', font=('Helvetica', 20, 'bold')).pack(side='left')
    ttk.Button(header, text='Back to Library', command=close).pack(side='right')
    toolbar = ttk.Frame(host, padding=(8, 2))
    toolbar.pack(fill='x')
    ttk.Label(toolbar, text='Search').pack(side='left', padx=(0, 6))
    ttk.Entry(toolbar, textvariable=query, width=24).pack(side='left')

    viewport = tk.Frame(host, bg=dark)
    viewport.pack(fill='both', expand=True, padx=6, pady=4)
    canvas = tk.Canvas(viewport, bg=dark, highlightthickness=0)
    hbar = ttk.Scrollbar(viewport, orient='horizontal', command=canvas.xview)
    vbar = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
    canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
    hbar.pack(side='bottom', fill='x')
    vbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    inside = tk.Frame(canvas, bg=dark)
    window_id = canvas.create_window((0, 0), window=inside, anchor='nw')
    inside.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))

    COLUMN_WIDTH = 290
    def size_columns(event=None):
        # Fixed width, content-driven height. Never stretch columns on resize.
        canvas.configure(scrollregion=canvas.bbox("all"))

    canvas.bind('<Configure>', size_columns)

    def scroll_page(event):
        # macOS trackpads send MouseWheel events to the widget under the cursor.
        # Scroll the single shared canvas, not an individual genre card.
        if getattr(event, 'state', 0) & 0x0001:
            canvas.xview_scroll(-1 if event.delta > 0 else 1, 'units')
        else:
            canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def scroll_horizontal(event):
        canvas.xview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def bind_scroll(widget):
        widget.bind('<MouseWheel>', scroll_page)
        widget.bind('<Shift-MouseWheel>', scroll_horizontal)
        widget.bind('<Button-4>', lambda e: (canvas.yview_scroll(-1, 'units'), 'break')[1])
        widget.bind('<Button-5>', lambda e: (canvas.yview_scroll(1, 'units'), 'break')[1])

    bind_scroll(canvas)
    bind_scroll(inside)

    def families():
        names = list(DEFAULT_GROUPS) + [g for g in custom_groups if g not in DEFAULT_GROUPS]
        genres = inventory(app.rows, custom_genres)
        grouped = {g: [] for g in names}
        for genre in genres:
            group = organization.get(genre, genre_group(genre))
            if group not in grouped:
                group = 'Other'
            grouped[group].append(genre)
        # Suggested subgenres are visible even if no tracks currently use them.
        for group, suggestions in SUGGESTED.items():
            for name in suggestions:
                if name not in grouped[group]:
                    grouped[group].append(name)
        for group in grouped:
            if group not in grouped[group]:
                grouped[group].insert(0, group)
            grouped[group] = sorted(set(grouped[group]), key=lambda x: (x != group, x.casefold()))
        return grouped, genres

    def selected_count():
        return len(chosen)

    def refresh_status(note=None):
        if note:
            status.set(note)
        else:
            status.set(f'{selected_count()} subgenres selected · Save writes Genre = family / Composer = original')
        pending.set("● Unsaved tag changes" if chosen else "No pending tag changes")

    def dark_action(parent, title, callback, *, bg=panel, color=fg, bold=False, pad_y=7):
        """Clickable Label instead of macOS Aqua tk.Button (which ignores dark bg/fg)."""
        label = tk.Label(parent, text=title, bg=bg, fg=color,
                             font=('Helvetica', 12, 'bold' if bold else 'normal'),
                             anchor='w', justify='left', padx=10, pady=pad_y,
                             cursor='hand2', highlightthickness=0, borderwidth=0)
        label.bind('<Button-1>', lambda _event: callback())
        label.bind('<Enter>', lambda _event: label.configure(bg='#45403A' if bg != panel else '#363B44'))
        label.bind('<Leave>', lambda _event: label.configure(bg=bg))
        bind_scroll(label)
        return label

    def drag_target(x_root, y_root):
        """Find the family under the pointer, even when over a child label."""
        for group, column in family_widgets.items():
            if (column.winfo_rootx() <= x_root < column.winfo_rootx() + column.winfo_width()
                    and column.winfo_rooty() <= y_root < column.winfo_rooty() + column.winfo_height()):
                return group
        return None

    def drag_start(event, group, name):
        drag.update(source=(group, name), start=(event.x_root, event.y_root),
                    moved=False, target=None)

    def drag_motion(event):
        if not drag['source'] or not drag['start']:
            return
        x, y = drag['start']
        if abs(event.x_root - x) + abs(event.y_root - y) < 9 and not drag['moved']:
            return
        drag['moved'] = True
        # Edge scrolling permits cross-column drops without grabbing a scrollbar.
        edge = 38
        left = canvas.winfo_rootx()
        right = left + canvas.winfo_width()
        if event.x_root > right - edge:
            canvas.xview_scroll(2, 'units')
        elif event.x_root < left + edge:
            canvas.xview_scroll(-2, 'units')
        top = canvas.winfo_rooty()
        bottom = top + canvas.winfo_height()
        if event.y_root > bottom - edge:
            canvas.yview_scroll(2, 'units')
        elif event.y_root < top + edge:
            canvas.yview_scroll(-2, 'units')
        target = drag_target(event.x_root, event.y_root)
        if target != drag['target']:
            drag['target'] = target
            for group, column in family_widgets.items():
                column.configure(highlightbackground=yellow if group == target else '#383B42',
                                 highlightthickness=2 if group == target else 1)

    def drag_end(event):
        source = drag['source']
        moved = drag['moved']
        target = drag_target(event.x_root, event.y_root) if moved else None
        drag.update(source=None, start=None, moved=False, target=None)
        if not source:
            return
        group, name = source
        if moved:
            if target and target != group:
                # Organization is preference-only; no music file is written here.
                organization[name] = target
                chosen.discard((group, name))
                app.save_preferences()
                redraw()
                refresh_status(f'Moved {name} to {target} · no music files changed')
            else:
                redraw()
        else:
            key = (group, name)
            if key in chosen:
                chosen.remove(key)
            else:
                chosen.add(key)
            redraw()

    def finish_drag(event):
        if drag['source']:
            drag_end(event)
        # Keep only a single active root-level drag binding per gesture.
        for key in ('<B1-Motion>', '<ButtonRelease-1>'):
            binding = drag.get('root_' + key)
            if binding:
                try: app.root.unbind_all(key)
                except Exception: pass
                drag['root_' + key] = None

    def redraw(*_):
        for widget in inside.winfo_children():
            widget.destroy()
        family_widgets.clear()
        grouped, genres = families()
        search = query.get().strip().casefold()
        for index, (group, names) in enumerate(grouped.items()):
            column = tk.Frame(inside, bg=panel, width=COLUMN_WIDTH, padx=8, pady=8,
                              highlightbackground='#383B42', highlightthickness=1)
            column.grid_propagate(True)
            column.grid(row=0, column=index, sticky='n', padx=5, pady=5)
            bind_scroll(column)
            shown = [name for name in names if not search or search in name.casefold() or search in group.casefold()]
            all_selected = bool(shown) and all((group, name) in chosen for name in shown)
            def choose_family(g=group, entries=tuple(shown)):
                if all((g, name) in chosen for name in entries):
                    chosen.difference_update((g, name) for name in entries)
                else:
                    chosen.update((g, name) for name in entries)
                redraw()
            heading = dark_action(column, ('☑ ' if all_selected else '□ ') + group,
                                  choose_family, bg='#3E3823' if all_selected else '#30333A',
                                  color=yellow, bold=True, pad_y=10)
            heading.pack(fill='x')
            family_widgets[group] = column
            for name in shown:
                is_selected = (group, name) in chosen
                btn = dark_action(column,
                                  ('☑ ' if is_selected else '□ ') + f'{name}  ({len(genres.get(name, []))})',
                                  lambda: None, bg='#3E3823' if is_selected else panel,
                                  color=fg, pad_y=6)
                # A release without motion selects; a drag moves the subgenre.
                # Avoid redrawing during ButtonPress because it destroys the widget.
                btn.unbind('<Button-1>')
                # Bind on the root while dragging: Tk labels stop receiving motion
                # and release once the pointer crosses into another column.
                def start_drag(e, g=group, n=name):
                    drag_start(e, g, n)
                    drag['root_<B1-Motion>'] = app.root.bind_all('<B1-Motion>', drag_motion, add='+')
                    drag['root_<ButtonRelease-1>'] = app.root.bind_all('<ButtonRelease-1>', finish_drag, add='+')
                btn.bind('<ButtonPress-1>', start_drag)
                btn.bind('<B1-Motion>', drag_motion)
                btn.bind('<ButtonRelease-1>', finish_drag)
                btn.pack(fill='x', pady=1)
            dark_action(column, '+ Add subgenre', lambda g=group: add_genre(g),
                        bg=panel, color=yellow).pack(fill='x', pady=(10, 0))
        inside.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox('all'))
        refresh_status()

    def add_genre(group):
        name = simpledialog.askstring('Add subgenre', f'New subgenre under {group}:', parent=host)
        if not name or not name.strip():
            return
        name = name.strip()
        known = set(inventory(app.rows, custom_genres)) | set(organization) | set(DEFAULT_GROUPS)
        for entries in SUGGESTED.values(): known.update(entries)
        if is_duplicate_genre(name, known):
            messagebox.showwarning('Duplicate genre', f'"{name}" already exists (or is a spelling variant).', parent=host)
            return
        custom_genres.append(name)
        organization[name] = group
        app.save_preferences()
        redraw()

    def add_group():
        name = simpledialog.askstring('Add main genre', 'New main genre name:', parent=host)
        if not name or not name.strip():
            return
        name = name.strip()
        if is_duplicate_genre(name, set(DEFAULT_GROUPS) | set(custom_groups) | set(organization)):
            messagebox.showwarning('Duplicate main genre', f'"{name}" already exists (or is a spelling variant).', parent=host)
            return
        custom_groups.append(name)
        app.save_preferences()
        redraw()

    def write_changes():
        # No preview or confirmation by design. The only mutation trigger is Save.
        assignments = {name: group for group, name in chosen}
        changes_by_path = plan_genre_writes(app.rows, assignments)
        if not changes_by_path:
            refresh_status('No tracks require changes for the selected subgenres.')
            return
        journal, errors = [], []
        for path, changes in changes_by_path.items():
            row = app.rows[path]
            before = {'genre': row.get('genre', ''), 'composer': row.get('composer', '')}
            try:
                safe_write(path, changes, {}, write_any_tags, read_any_track,
                           app.data_dir / 'metadata_recovery', expected=row.get('disk_fingerprint'))
                journal.append({'path': path, 'before': before, 'after': changes})
                row.update(read_any_track(path))
                row['status'] = 'Genre Cleanup — saved'
                app.refresh(path)
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')
        if journal:
            app.store.history('genre_cleanup_written', {'files': journal})
        app.persist_library()
        chosen.clear()
        redraw()
        refresh_status(f'Saved {len(journal)} files · {len(errors)} errors' + (f' · {errors[0]}' if errors else ''))

    ttk.Button(toolbar, text='+ Add Main Genre', command=add_group).pack(side='left', padx=(12, 4))
    ttk.Button(toolbar, text='Clear Selection', command=lambda: (chosen.clear(), redraw())).pack(side='left')
    footer = ttk.Frame(host, padding=(8, 4))
    footer.pack(fill='x')
    ttk.Label(footer, textvariable=status, style='Muted.TLabel').pack(side='left', fill='x', expand=True)
    ttk.Label(toolbar, textvariable=pending, style='Muted.TLabel').pack(side='right', padx=8)
    ttk.Button(footer, text='History / Restore', command=app.genre_restore_history).pack(side='right', padx=5)
    ttk.Button(footer, text='Save Changes', command=write_changes, style='Accent.TButton').pack(side='right', padx=5)
    # A compact, independent control in each bottom corner; both default collapsed.
    task_toggle = tk.Label(host, text='▸ Tasks', bg='#30353E', fg=yellow, cursor='hand2', padx=10, pady=5)
    task_toggle.pack(side='bottom', anchor='w')
    def toggle_tasks(_event=None):
        if app._feedback_bar.winfo_manager():
            app._feedback_bar.pack_forget()
            task_toggle.configure(text='▸ Tasks')
        else:
            app._feedback_bar.pack(fill='x', before=app.player_panel)
            task_toggle.configure(text='▾ Tasks')
    task_toggle.bind('<Button-1>', toggle_tasks)
    player_toggle = tk.Label(host, text='▸ Player', bg='#30353E', fg=yellow, cursor='hand2', padx=10, pady=5)
    player_toggle.pack(side='bottom', anchor='e')
    def toggle_player(_event=None):
        if app.player_panel.winfo_manager():
            app.player_panel.pack_forget()
            player_toggle.configure(text='▸ Player')
        else:
            app.player_panel.pack(side='bottom', fill='x', padx=12, pady=(0, 5))
            app.set_player_collapsed(False)
            player_toggle.configure(text='▾ Player')
    player_toggle.bind('<Button-1>', toggle_player)
    query.trace_add('write', redraw)
    redraw()
