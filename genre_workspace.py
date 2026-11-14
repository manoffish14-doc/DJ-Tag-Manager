"""In-window genre organization and deliberate, recoverable metadata edits."""
from collections import defaultdict
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

DEFAULT_GROUPS = ('Hip Hop', 'R&B', 'Pop', 'Classic Rock', 'Rock', 'African', 'Other')


def inventory(rows, custom=()):
    result = defaultdict(list)
    for path, row in rows.items():
        name = str(row.get('genre') or '').strip()
        if name:
            result[name].append(path)
    for name in custom:
        if name:
            result.setdefault(name, [])
    return dict(result)


def open_genre_workspace(app):
    from cleanup_engine import genre_group
    from app import read_any_track, write_any_tags
    from metadata_safety import safe_write

    if getattr(app, '_genre_workspace', None) is not None:
        if app._genre_workspace.winfo_exists():
            return
    table = app._library_table_frame
    table.pack_forget()
    host = ttk.Frame(app.content)
    host.pack(side='left', fill='both', expand=True)
    app._genre_workspace = host
    organization = app.extra_settings.setdefault('genre_organization', {})
    custom_groups = app.extra_settings.setdefault('genre_custom_groups', [])
    custom_genres = app.extra_settings.setdefault('genre_custom_genres', [])
    selected_group = tk.StringVar(value='All Genres')
    query = tk.StringVar()
    destination = tk.StringVar(value='Other')
    replacement = tk.StringVar()
    preserve = tk.BooleanVar(value=False)
    status = tk.StringVar(value='Select one or more genres to see affected tracks.')
    palette = {'bg': '#15171B', 'fg': '#F2F3F5', 'select': '#48412A'}

    def close():
        host.destroy()
        app._genre_workspace = None
        table.pack(side='left', fill='both', expand=True)

    head = ttk.Frame(host, padding=(12, 10))
    head.pack(fill='x')
    ttk.Label(head, text='Genre Cleanup', font=('Helvetica', 20, 'bold')).pack(side='left')
    ttk.Button(head, text='Back to Library', command=close).pack(side='right')
    ttk.Label(host, text='Organize genres without modifying audio files. Confirm before changing MP3 tags.', style='Muted.TLabel').pack(anchor='w', padx=14)
    searchbar = ttk.Frame(host, padding=(12, 10))
    searchbar.pack(fill='x')
    ttk.Label(searchbar, text='Search genres').pack(side='left', padx=(0, 8))
    ttk.Entry(searchbar, textvariable=query).pack(side='left', fill='x', expand=True)

    columns = ttk.Frame(host, padding=(10, 2))
    columns.pack(fill='both', expand=True)
    groups_frame = ttk.Frame(columns)
    groups_frame.pack(side='left', fill='both', expand=False, padx=5)
    genres_frame = ttk.Frame(columns)
    genres_frame.pack(side='left', fill='both', expand=True, padx=5)
    tracks_frame = ttk.Frame(columns)
    tracks_frame.pack(side='left', fill='both', expand=True, padx=5)
    ttk.Label(groups_frame, text='Groups').pack(anchor='w')
    ttk.Label(genres_frame, text='Genres (multi-select)').pack(anchor='w')
    ttk.Label(tracks_frame, text='Affected tracks').pack(anchor='w')
    group_list = tk.Listbox(groups_frame, width=19, exportselection=False, bg=palette['bg'], fg=palette['fg'], selectbackground=palette['select'], relief='flat')
    group_list.pack(fill='both', expand=True)
    genre_list = tk.Listbox(genres_frame, selectmode='extended', exportselection=False, bg=palette['bg'], fg=palette['fg'], selectbackground=palette['select'], relief='flat')
    genre_list.pack(fill='both', expand=True)
    track_list = tk.Listbox(tracks_frame, bg=palette['bg'], fg=palette['fg'], selectbackground=palette['select'], relief='flat')
    track_list.pack(fill='both', expand=True)
    shown_genres = []
    shown_groups = []

    def chosen():
        return [shown_genres[i] for i in genre_list.curselection() if i < len(shown_genres)]

    def update_tracks(*_):
        paths = list(dict.fromkeys(p for genre in chosen() for p in inventory(app.rows, custom_genres).get(genre, [])))
        track_list.delete(0, 'end')
        for path in paths:
            row = app.rows[path]
            track_list.insert('end', f"{row.get('artist', '')} — {row.get('title', Path(path).stem)}")
        status.set(f'{len(paths)} tracks selected · {len(chosen())} genres')

    def redraw(*_):
        previous = set(chosen())
        genres = inventory(app.rows, custom_genres)
        group_names = ['All Genres', *DEFAULT_GROUPS, *[g for g in custom_groups if g not in DEFAULT_GROUPS]]
        current = selected_group.get()
        if current not in group_names:
            current = 'All Genres'
            selected_group.set(current)
        shown_groups[:] = group_names
        group_list.delete(0, 'end')
        for group in group_names:
            count = sum(len(paths) for name, paths in genres.items() if group == 'All Genres' or organization.get(name, genre_group(name)) == group)
            group_list.insert('end', f'{group}  ({count})')
        group_list.selection_set(group_names.index(current))
        shown_genres[:] = sorted((name for name in genres if (current == 'All Genres' or organization.get(name, genre_group(name)) == current) and query.get().casefold() in name.casefold()), key=str.casefold)
        genre_list.delete(0, 'end')
        for i, name in enumerate(shown_genres):
            genre_list.insert('end', f'{name}  ({len(genres[name])})')
            if name in previous:
                genre_list.selection_set(i)
        update_tracks()

    def choose_group(_=None):
        sel = group_list.curselection()
        if sel:
            selected_group.set(shown_groups[sel[0]])
            redraw()

    def add_group():
        name = simpledialog.askstring('New group', 'Group name:', parent=host)
        if not name or not name.strip():
            return
        name = name.strip()
        if name not in DEFAULT_GROUPS and name not in custom_groups:
            custom_groups.append(name)
            app.save_preferences()
        selected_group.set(name)
        destination.set(name)
        redraw()

    def rename_group():
        old = selected_group.get()
        if old == 'All Genres' or old in DEFAULT_GROUPS:
            return messagebox.showinfo('Genre groups', 'Select a custom group to rename.', parent=host)
        name = simpledialog.askstring('Rename group', 'New group name:', initialvalue=old, parent=host)
        if not name or not name.strip() or name.strip() == old:
            return
        name = name.strip()
        if name in DEFAULT_GROUPS or name in custom_groups:
            return messagebox.showwarning('Genre groups', 'That group already exists.', parent=host)
        custom_groups.remove(old)
        custom_groups.append(name)
        for genre, group in list(organization.items()):
            if group == old:
                organization[genre] = name
        selected_group.set(name)
        app.save_preferences()
        redraw()

    def add_genre():
        name = simpledialog.askstring('New genre', 'Genre name (organization only; does not edit music files):', parent=host)
        if not name or not name.strip():
            return
        name = name.strip()
        if name not in inventory(app.rows, custom_genres):
            custom_genres.append(name)
        if selected_group.get() != 'All Genres':
            organization[name] = selected_group.get()
        app.save_preferences()
        redraw()

    def move_genres():
        names = chosen()
        group = destination.get().strip()
        if not names or not group:
            return messagebox.showwarning('Organize genres', 'Select genres and a destination group.', parent=host)
        if group not in DEFAULT_GROUPS and group not in custom_groups:
            custom_groups.append(group)
        for name in names:
            organization[name] = group
        app.save_preferences()
        redraw()
        status.set(f'Moved {len(names)} genre labels into {group}; no audio files changed.')

    def write_genres():
        names = chosen()
        target = replacement.get().strip()
        if not names or not target:
            return messagebox.showwarning('Rename genres', 'Select genres and enter a replacement.', parent=host)
        genres = inventory(app.rows, custom_genres)
        paths = list(dict.fromkeys(path for name in names for path in genres[name]))
        if not paths:
            return messagebox.showinfo('Rename genres', 'No tracks use the selected genres. You can organize empty genres without writing files.', parent=host)
        preview = '\n'.join(f'  {name} ({len(genres[name])}) → {target}' for name in names[:12])
        if not messagebox.askyesno('Confirm genre changes', f'Preview:\n{preview}\n\nWrite Genre = {target} to {len(paths)} music files?\nBackups and history will be recorded.', parent=host):
            return
        if preserve.get() and not messagebox.askyesno('Composer / Subgenre', 'Preserving the original Genre in Composer will overwrite existing Composer tags. Continue?', parent=host):
            return
        journal, errors = [], []
        for path in paths:
            row = app.rows[path]
            before = {'genre': row.get('genre', ''), 'composer': row.get('composer', '')}
            changes = {'genre': target}
            if preserve.get():
                changes['composer'] = before['genre']
            try:
                safe_write(path, changes, {}, write_any_tags, read_any_track, app.data_dir / 'metadata_recovery', expected=row.get('disk_fingerprint'))
                journal.append({'path': path, 'before': before, 'after': changes})
                row.update(read_any_track(path))
                row['status'] = 'Genre Cleanup — saved'
                app.refresh(path)
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')
        if journal:
            app.store.history('genre_cleanup_written', {'files': journal})
        app.persist_library()
        redraw()
        messagebox.showinfo('Genre Cleanup', f'{len(journal)} files updated; {len(errors)} failed.' + ('\n' + '\n'.join(errors[:5]) if errors else ''), parent=host)

    def drop_on_group(event):
        """Drag selected genres onto a group to organize them, without writing tags."""
        names = chosen()
        if not names:
            return
        target = host.winfo_containing(event.x_root, event.y_root)
        if target is not group_list:
            return
        index = group_list.nearest(event.y_root - group_list.winfo_rooty())
        if not 0 <= index < len(shown_groups):
            return
        group = shown_groups[index]
        if group == 'All Genres':
            return
        for name in names:
            organization[name] = group
        app.save_preferences()
        selected_group.set(group)
        redraw()
        status.set(f'Moved {len(names)} genre labels into {group}; no audio files changed.')

    genre_list.bind('<ButtonRelease-1>', drop_on_group, add='+')
    group_list.bind('<<ListboxSelect>>', choose_group)
    genre_list.bind('<<ListboxSelect>>', update_tracks)
    query.trace_add('write', redraw)
    group_buttons = ttk.Frame(host, padding=(12, 5))
    group_buttons.pack(fill='x')
    ttk.Button(group_buttons, text='+ New Group', command=add_group).pack(side='left', padx=3)
    ttk.Button(group_buttons, text='Rename Group', command=rename_group).pack(side='left', padx=3)
    ttk.Button(group_buttons, text='+ New Genre', command=add_genre).pack(side='left', padx=3)
    ttk.Label(group_buttons, text='Move selected genres to:').pack(side='left', padx=(14, 5))
    group_combo = ttk.Combobox(group_buttons, textvariable=destination, values=list(DEFAULT_GROUPS) + list(custom_groups), width=17)
    group_combo.pack(side='left')
    ttk.Button(group_buttons, text='Move', command=move_genres).pack(side='left', padx=5)

    edit = ttk.Frame(host, padding=(12, 8))
    edit.pack(fill='x')
    ttk.Label(edit, text='Rename / merge selected genres:').pack(side='left', padx=(0, 7))
    ttk.Entry(edit, textvariable=replacement, width=22).pack(side='left', padx=4)
    ttk.Checkbutton(edit, text='Copy original Genre to Composer', variable=preserve).pack(side='left', padx=8)
    ttk.Button(edit, text='Preview & Save to Files', command=write_genres, style='Accent.TButton').pack(side='left', padx=5)
    ttk.Button(edit, text='History / Restore', command=app.genre_restore_history).pack(side='right')
    ttk.Label(host, textvariable=status, style='Muted.TLabel').pack(anchor='w', padx=14, pady=(0, 8))
    redraw()
