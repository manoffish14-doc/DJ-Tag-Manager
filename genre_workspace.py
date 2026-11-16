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


def family_track_count(group, grouped, genres):
    """Count distinct track paths across all subgenres of a family."""
    return len({path for name in (group, *grouped.get(group, ())) for path in genres.get(name, ())})


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
    task_related = []
    for candidate in (getattr(app, '_queue_bar', None), getattr(app, 'queue_bar', None)):
        if candidate is not None and candidate.winfo_manager() == 'pack':
            task_related.append((candidate, candidate.pack_info()))
            candidate.pack_forget()
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
    genre_order = app.extra_settings.setdefault('genre_main_order', [])
    # Seed the familiar families without changing any track metadata.
    # Repair old cross-family assignments only for canonical duplicates.
    for group, names in SUGGESTED.items():
        for name in names:
            organization.setdefault(name, group)
    for group in DEFAULT_GROUPS:
        organization[group] = group
    # A genre name belongs to exactly one family, including spelling variants.
    seen = {}
    for name in list(organization):
        key = canonical_genre(name)
        if key in seen and name != seen[key]:
            del organization[name]
        else:
            seen[key] = name
    query = tk.StringVar()
    status = tk.StringVar(value='Select a genre family or individual subgenres, then Save Changes.')
    chosen = set()  # (parent, subgenre); selection is independent of file writes
    selected_families = set()  # Empty families can be selected for organization
    family_widgets = {}
    chip_widgets = {}
    reorder = {'source': None, 'start': None, 'moved': False, 'target': None}
    pending = tk.StringVar(value="")
    show_all = tk.BooleanVar(value=True)
    target_genre = tk.StringVar(value='')
    wheel_remainder = [0.0]
    refresh_job = [None]
    drag = {"source": None, "start": None, "moved": False, "target": None}
    dark, panel, fg, yellow = '#15171B', '#22252B', '#F2F3F5', '#FACC15'

    def close():
        unbind_global_scroll()
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
        for widget, options in task_related:
            widget.pack(**options)

    app._close_genre_workspace = close
    header = ttk.Frame(host, padding=(8, 2))
    header.pack(fill='x')
    ttk.Label(header, text='Genre Cleanup', font=('Helvetica', 20, 'bold')).pack(side='left')
    toolbar = ttk.Frame(host, padding=(8, 2))
    toolbar.pack(fill='x')
    ttk.Label(toolbar, text='Search').pack(side='left', padx=(0, 6))
    ttk.Entry(toolbar, textvariable=query, width=24).pack(side='left')

    viewport = tk.Frame(host, bg=dark)
    viewport.pack(fill='both', expand=True, padx=6, pady=4)
    canvas = tk.Canvas(viewport, bg=dark, highlightthickness=0)
    vbar = ttk.Scrollbar(viewport, orient='vertical', command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    vbar.pack(side='right', fill='y')
    canvas.pack(side='left', fill='both', expand=True)
    inside = tk.Frame(canvas, bg=dark)
    window_id = canvas.create_window((0, 0), window=inside, anchor='nw')
    inside.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))

    COLUMN_WIDTH = 270
    COLUMN_GAP = 12
    def size_columns(event=None):
        # Match the canvas viewport so the grid never scrolls sideways.
        canvas.itemconfigure(window_id, width=canvas.winfo_width())
        canvas.configure(scrollregion=canvas.bbox('all'))
        if event is not None and not drag['source']:
            if refresh_job[0] is not None:
                host.after_cancel(refresh_job[0])
            refresh_job[0] = host.after(100, redraw)

    canvas.bind('<Configure>', size_columns)

    def scroll_page(event):
        # Aqua sends small pixel deltas (often 1-10), unlike Windows 120-unit ticks.
        # Move in pixels to preserve precise trackpad motion and clamp to content.
        delta = float(getattr(event, 'delta', 0) or 0)
        if not delta:
            return 'break'
        content_height = max(1, inside.winfo_reqheight())
        visible_height = canvas.winfo_height()
        max_offset = max(0, content_height - visible_height)
        if not max_offset:
            return 'break'
        current = canvas.yview()[0] * content_height
        pixels = (-delta * (2.0 if abs(delta) < 120 else 0.55))
        canvas.yview_moveto(max(0, min(max_offset, current + pixels)) / content_height)
        return 'break'

    def bind_scroll(widget):
        widget.bind('<MouseWheel>', scroll_page, add='+')
        widget.bind('<Shift-MouseWheel>', scroll_page, add='+')
        widget.bind('<Button-4>', lambda e: (canvas.yview_scroll(-2, 'units'), 'break')[1], add='+')
        widget.bind('<Button-5>', lambda e: (canvas.yview_scroll(2, 'units'), 'break')[1], add='+')

    # Global scrolling is only active while the pointer is over Genre Cleanup.
    # This catches macOS events sent to nested ttk/tk widgets.
    def global_scroll(event):
        widget = app.root.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is viewport or widget is canvas or widget is inside:
                return scroll_page(event)
            widget = getattr(widget, 'master', None)
    scroll_binding = app.root.bind_all('<MouseWheel>', global_scroll, add='+')
    def unbind_global_scroll():
        if global_click_id:
            try: app.root.unbind_class('all', '<Button-1>', global_click_id)
            except Exception: pass
        if scroll_binding:
            try: app.root.unbind_all('<MouseWheel>')
            except Exception: pass

    bind_scroll(canvas)
    bind_scroll(inside)

    def families():
        known = [g for g in DEFAULT_GROUPS if g != 'Other'] + [g for g in custom_groups if g not in DEFAULT_GROUPS and g != 'Other']
        names = [g for g in genre_order if g in known and g != 'Other']
        names += [g for g in known if g not in names]
        names.append('Other')
        genres = inventory(app.rows, custom_genres)
        grouped = {g: [] for g in names}
        candidates = list(genres)
        for suggestions in SUGGESTED.values():
            candidates.extend(suggestions)
        unique = {}
        for name in candidates:
            key = canonical_genre(name)
            # Prefer actual library spelling when multiple aliases exist.
            if key not in unique or (genres.get(name) and not genres.get(unique[key])):
                unique[key] = name
        for name in unique.values():
            if name in names:
                continue  # Main genres must not appear as their own subgenres.
            group = organization.get(name)
            if group not in grouped:
                group = genre_group(name)
            if group not in grouped:
                group = 'Other'
            grouped[group].append(name)
        for group in grouped:
            grouped[group] = sorted(grouped[group], key=lambda x: (canonical_genre(x) != canonical_genre(group), x.casefold()))
        return grouped, genres

    def selected_count():
        return len(chosen) + len(selected_families)

    def refresh_status(note=None):
        if note:
            status.set(note)
        else:
            status.set(f'{len(chosen)} subgenres · {len(selected_families)} empty families selected · Genre = family / Composer = original')
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
        # Edge scrolling is vertical only; columns wrap instead of scrolling sideways.
        edge = 38
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
                # Never duplicate the same subgenre in multiple families.
                for alias in list(organization):
                    if canonical_genre(alias) == canonical_genre(name):
                        organization.pop(alias, None)
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
        # Remove only our handlers; never remove other app-level bindings.
        for key in ('<B1-Motion>', '<ButtonRelease-1>'):
            binding = drag.pop('root_' + key, None)
            if binding:
                try: app.root.unbind(key, binding)
                except Exception: pass

    def redraw(*_):
        previous_y = canvas.yview()[0] if canvas.winfo_exists() else 0.0
        for widget in inside.winfo_children():
            widget.destroy()
        family_widgets.clear()
        chip_widgets.clear()
        grouped, genres = families()
        search = query.get().strip().casefold()
        visible = []
        for group, names in grouped.items():
            # Show All controls families, never the zero-track subgenre inventory.
            # Searching can surface a predefined empty subgenre for discovery.
            eligible = [name for name in names if genres.get(name) or (search and (search in name.casefold()))]
            shown = [name for name in eligible if not search or search in name.casefold() or search in group.casefold()]
            if not shown and (not show_all.get() or search):
                continue
            # A family is nonempty if any of its genres has songs in this library.
            visible.append((group, shown))
        available = max(1, canvas.winfo_width() - 12)
        columns = max(1, min(3, available // (COLUMN_WIDTH + COLUMN_GAP)))
        # Use the full row width while keeping cards within a reasonable size.
        card_width = max(180, (available - 10 * columns) // columns)
        # Independent column stacks: a tall family never pushes down its neighbors.
        for child in inside.winfo_children():
            child.destroy()
        stacks = []
        for c in range(columns):
            inside.grid_columnconfigure(c, weight=1, uniform='genre')
            stack = tk.Frame(inside, bg=dark)
            stack.grid(row=0, column=c, sticky='new', padx=5)
            stacks.append(stack)
        for c in range(columns, 3):
            inside.grid_columnconfigure(c, weight=0, uniform='')
        heights = [0] * columns
        for index, (group, shown) in enumerate(visible):
            # Balance the vertical stacks, while keeping Other last.
            slot = min(range(columns), key=lambda c: (heights[c], c))
            column = tk.Frame(stacks[slot], bg=panel, padx=8, pady=8,
                              highlightbackground='#383B42', highlightthickness=1)
            column.pack(fill='x', pady=(0, 16))
            bind_scroll(column)
            all_selected = group in selected_families
            def choose_family(g=group, entries=tuple(shown)):
                if g in selected_families:
                    selected_families.remove(g)
                else:
                    selected_families.add(g)
                redraw()
            heading = dark_action(column, ('☑ ' if all_selected else '□ ') +
                                  f'{group}  ({family_track_count(group, grouped, genres)})',
                                  choose_family, bg='#3E3823' if all_selected else '#30333A',
                                  color=yellow, bold=True, pad_y=9)
            heading._genre_click_target = True
            heading.pack(fill='x')
            handle = tk.Label(heading, text='⠿', bg='#3E3823' if all_selected else '#30333A',
                              fg=yellow, cursor='fleur', padx=7,
                              font=('Helvetica', 15, 'bold'))
            handle.pack(side='right')
            handle._genre_click_target = True
            def begin_reorder(event, g=group):
                reorder.update(source=g, start=(event.x_root, event.y_root), moved=False, target=None)
                return 'break'
            def move_reorder(event):
                if not reorder['source'] or not reorder['start']:
                    return 'break'
                x, y = reorder['start']
                if abs(event.x_root-x) + abs(event.y_root-y) > 7:
                    reorder['moved'] = True
                if reorder['moved']:
                    target = drag_target(event.x_root, event.y_root)
                    if target == 'Other' or reorder['source'] == 'Other':
                        target = None
                    reorder['target'] = target
                    for g, card in family_widgets.items():
                        card.configure(highlightbackground=yellow if g == target else '#383B42',
                                       highlightthickness=2 if g == target else 1)
                return 'break'
            def end_reorder(event):
                source = reorder['source']
                target = reorder['target'] if reorder['moved'] else None
                reorder.update(source=None, start=None, moved=False, target=None)
                if source and target and source != target:
                    current = [g for g in families()[0] if g != 'Other']
                    if source in current and target in current:
                        current.remove(source)
                        current.insert(current.index(target), source)
                        genre_order[:] = current
                        app.save_preferences()
                        redraw()
                        refresh_status(f'Moved {source} before {target} · display order saved')
                else:
                    redraw()
                return 'break'
            handle.bind('<ButtonPress-1>', begin_reorder)
            handle.bind('<B1-Motion>', move_reorder)
            handle.bind('<ButtonRelease-1>', end_reorder)
            family_widgets[group] = column
            # Compact chips wrap by their own text widths, rather than filling rows.
            chip_area = tk.Frame(column, bg=panel)
            chip_area.pack(fill='x', pady=(6, 0))
            bind_scroll(chip_area)
            chip_widgets[group] = []
            for name in shown:
                is_selected = (group, name) in chosen
                btn = dark_action(chip_area,
                                  ('☑ ' if is_selected else '□ ') + f'{name} ({len(genres.get(name, []))})',
                                  lambda: None, bg='#3E3823' if is_selected else '#30333A',
                                  color=fg, pad_y=5)
                btn.unbind('<Button-1>')
                def start_drag(e, g=group, n=name):
                    drag_start(e, g, n)
                    drag['root_<B1-Motion>'] = app.root.bind('<B1-Motion>', drag_motion, add='+')
                    drag['root_<ButtonRelease-1>'] = app.root.bind('<ButtonRelease-1>', finish_drag, add='+')
                btn.bind('<ButtonPress-1>', start_drag)
                btn.bind('<B1-Motion>', drag_motion)
                btn.bind('<ButtonRelease-1>', finish_drag)
                btn._genre_click_target = True
                chip_widgets[group].append(btn)
            def layout_chips(e=None, group=group, area=chip_area):
                width = max(120, area.winfo_width() - 4)
                x, y, line_height = 0, 0, 0
                for chip in chip_widgets.get(group, []):
                    w = min(width, chip.winfo_reqwidth())
                    h = chip.winfo_reqheight()
                    if x and x + w > width:
                        x, y, line_height = 0, y + line_height + 5, 0
                    chip.place(x=x, y=y, width=w, height=h)
                    x += w + 5
                    line_height = max(line_height, h)
                area.configure(height=max(1, y + line_height))
            chip_area.bind('<Configure>', layout_chips, add='+')
            column.after_idle(layout_chips)
            # Estimate height for balancing; actual Tk geometry follows chip wrapping.
            estimated_chips = sum(max(65, 15 + len(n) * 7) for n in shown)
            lines = max(1, (estimated_chips + max(1, card_width - 20) - 1) // max(1, card_width - 20))
            heights[slot] += 64 + lines * 35 + 16
        inside.update_idletasks()
        canvas.configure(scrollregion=canvas.bbox('all'))
        canvas.yview_moveto(previous_y if inside.winfo_reqheight() > canvas.winfo_height() else 0)
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
        all_names = set(DEFAULT_GROUPS) | set(custom_groups) | set(organization) | set(inventory(app.rows, custom_genres))
        for names in SUGGESTED.values(): all_names.update(names)
        main_names = set(DEFAULT_GROUPS) | set(custom_groups)
        if is_duplicate_genre(name, main_names):
            messagebox.showwarning('Duplicate main genre', f'"{name}" is already a main genre.', parent=host)
            return
        existing_subgenre = next((n for n in all_names if canonical_genre(n) == canonical_genre(name)), None)
        if existing_subgenre:
            if not messagebox.askyesno('Promote subgenre',
                    f'"{existing_subgenre}" already exists as a subgenre.\n\n'
                    'Promote it to a main genre?',
                    parent=host):
                return
            name = existing_subgenre
        custom_groups.append(name)
        # Remove its old parent mapping; other subgenres stay where they are.
        for alias in list(organization):
            if canonical_genre(alias) == canonical_genre(name):
                organization.pop(alias, None)
        organization[name] = name
        chosen.clear()
        selected_families.clear()
        app.save_preferences()
        redraw()

    def write_changes():
        # No preview or confirmation by design. The only mutation trigger is Save.
        override = target_genre.get().strip()
        assignments = {name: (override or group) for group, name in chosen}
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
        selected_families.clear()
        redraw()
        refresh_status(f'Saved {len(journal)} files · {len(errors)} errors' + (f' · {errors[0]}' if errors else ''))

    ttk.Button(toolbar, text='+ Add Main Genre', command=add_group).pack(side='left', padx=(12, 4))
    ttk.Checkbutton(toolbar, text='Show All Genres', variable=show_all, command=redraw).pack(side='left', padx=(12, 4))
    # Clicking the blank canvas deselects everything, without a separate button.
    def clear_on_background(event):
        if drag['source'] is None and (chosen or selected_families):
            chosen.clear()
            selected_families.clear()
            redraw()
    def global_clear(event):
        widget = event.widget
        # Genre controls and their containers manage their own clicks.
        node = widget
        while node is not None:
            if getattr(node, '_genre_click_target', False) or node in family_widgets.values() or node in chip_widgets.values():
                return
            node = getattr(node, 'master', None)
        # Keep inputs and buttons functional; a click on them still clears the selection.
        if widget is not app.root and (chosen or selected_families):
            clear_on_background(event)

    global_click_id = app.root.bind_all('<Button-1>', global_clear, add='+')
    canvas.bind('<Button-1>', clear_on_background, add='+')
    inside.bind('<Button-1>', clear_on_background, add='+')
    header.bind('<Button-1>', clear_on_background, add='+')
    toolbar.bind('<Button-1>', clear_on_background, add='+')
    footer_clear_targets = []
    footer = ttk.Frame(host, padding=(8, 4))
    footer.pack(fill='x')
    footer.bind('<Button-1>', clear_on_background, add='+')
    ttk.Label(footer, textvariable=status, style='Muted.TLabel').pack(fill='x', pady=(0, 4))
    ttk.Label(toolbar, textvariable=pending, style='Muted.TLabel').pack(side='right', padx=8)
    actions = ttk.Frame(footer)
    actions.pack(fill='x')
    ttk.Label(actions, text='New Genre (optional):').pack(side='left', padx=(0, 5))
    ttk.Entry(actions, textvariable=target_genre, width=19).pack(side='left', fill='x', expand=True, padx=(0, 8))
    ttk.Button(actions, text='Save Changes', command=write_changes, style='Accent.TButton').pack(side='left', padx=(0, 5))
    ttk.Button(actions, text='History / Restore', command=app.genre_restore_history).pack(side='left')
    # A compact, independent control in each bottom corner; both default collapsed.
    task_toggle = tk.Label(host, text='▸ Tasks', bg='#30353E', fg=yellow, cursor='hand2', padx=10, pady=5)
    task_toggle.pack(side='bottom', anchor='w')
    def toggle_tasks(_event=None):
        if app._feedback_bar.winfo_manager():
            app._feedback_bar.pack_forget()
            task_toggle.configure(text='▸ Tasks')
        else:
            app._feedback_bar.pack(fill='x')
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
    host.bind('<Button-1>', clear_on_background, add='+')
    viewport.bind('<Button-1>', clear_on_background, add='+')
    query.trace_add('write', redraw)
    redraw()
