"""Lexicon-style vertical genre families with immediate, recoverable bulk writes."""
from collections import defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, simpledialog

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
    dark, panel, fg, yellow = '#15171B', '#22252B', '#F2F3F5', '#FACC15'

    def close():
        host.destroy()
        app._genre_workspace = None
        table.pack(side='left', fill='both', expand=True)
        for widget, pack_options in hidden:
            widget.pack(**pack_options)
        app.set_player_collapsed(prior_collapsed)

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

    def size_columns(event=None):
        # Four generously sized genre families per visible page; scroll for more.
        width = max(250, (canvas.winfo_width() - 42) // 4)
        height = max(320, canvas.winfo_height() - 22)
        for child in inside.winfo_children():
            child.configure(width=width, height=height)
        canvas.configure(scrollregion=canvas.bbox('all'))

    canvas.bind('<Configure>', size_columns)

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
            status.set(f'{selected_count()} subgenres selected · Save Changes writes Genre = family and Composer = original genre')

    def dark_action(parent, title, callback, *, bg=panel, color=fg, bold=False, pad_y=7):
        """Clickable Label instead of macOS Aqua tk.Button (which ignores dark bg/fg)."""
        label = tk.Label(parent, text=title, bg=bg, fg=color,
                             font=('Helvetica', 12, 'bold' if bold else 'normal'),
                             anchor='w', justify='left', padx=10, pady=pad_y,
                             cursor='hand2', highlightthickness=0, borderwidth=0)
        label.bind('<Button-1>', lambda _event: callback())
        label.bind('<Enter>', lambda _event: label.configure(bg='#45403A' if bg != panel else '#363B44'))
        label.bind('<Leave>', lambda _event: label.configure(bg=bg))
        return label

    def redraw(*_):
        for widget in inside.winfo_children():
            widget.destroy()
        family_widgets.clear()
        grouped, genres = families()
        search = query.get().strip().casefold()
        for index, (group, names) in enumerate(grouped.items()):
            column = tk.Frame(inside, bg=panel, width=max(250, (canvas.winfo_width() - 42) // 4),
                              height=max(320, canvas.winfo_height() - 22), padx=8, pady=8,
                              highlightbackground='#383B42', highlightthickness=1)
            column.pack_propagate(False)
            column.grid(row=0, column=index, sticky='ns', padx=5, pady=5)
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
                def toggle(g=group, n=name):
                    key = (g, n)
                    if key in chosen:
                        chosen.remove(key)
                    else:
                        chosen.add(key)
                    redraw()
                btn = dark_action(column,
                                  ('☑ ' if is_selected else '□ ') + f'{name}  ({len(genres.get(name, []))})',
                                  toggle, bg='#3E3823' if is_selected else panel,
                                  color=fg, pad_y=6)
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
        if name not in inventory(app.rows, custom_genres):
            custom_genres.append(name)
        organization[name] = group
        app.save_preferences()
        redraw()

    def add_group():
        name = simpledialog.askstring('Add main genre', 'New main genre name:', parent=host)
        if not name or not name.strip():
            return
        name = name.strip()
        if name not in DEFAULT_GROUPS and name not in custom_groups:
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
    ttk.Button(footer, text='History / Restore', command=app.genre_restore_history).pack(side='right', padx=5)
    ttk.Button(footer, text='Save Changes', command=write_changes, style='Accent.TButton').pack(side='right', padx=5)
    query.trace_add('write', redraw)
    redraw()
