import csv
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date, timedelta

try:
    import winsound
except Exception:
    winsound = None

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except Exception:
    PIL_OK = False
    Image = None
    ImageTk = None

APP_TITLE = "Weighted Progress Tracker — v1.0"
AUTOSAVE_FILE = "progress_data_1.0.json"
DATE_FMT = "%Y-%m-%d"
PROGRESS_MODES = ["Weighted", "Unweighted", "Hours-weighted"]
STATUS_OPTIONS = ["Not started", "In progress", "Blocked", "Done"]

def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, DATE_FMT).date()
    except ValueError:
        return None

def normalize_tags(s):
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",")]
    return [p for p in parts if p]

class ScrollableFrame(ttk.Frame):
    def __init__(self, master, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)
        self.inner = ttk.Frame(self.canvas)
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vscroll.grid(row=0, column=1, sticky="ns")
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self._win, width=event.width)

class ProgressTracker(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=16)
        self.master = master
        self.items = []
        # Settings / state
        self.dark_mode = tk.BooleanVar(value=True)
        self.sort_key = tk.StringVar(value="Due Date")
        self.sort_ascending = tk.BooleanVar(value=True)
        self.autosave_on = tk.BooleanVar(value=True)
        # Progress / notifications
        self.progress_mode = tk.StringVar(value=PROGRESS_MODES[0])
        self.notify_enabled = tk.BooleanVar(value=True)
        self.notify_days = tk.IntVar(value=3)
        self.notify_interval_sec = 60
        self._already_notified = set()
        # Weekly view + tags/filter
        self.week_panel = None
        self.week_cols = []
        self.filter_tag = tk.StringVar(value="All")
        # Goal (banner-like area at top)
        self.goal_text = ""          # persisted string
        self.goal_image_path = None  # persisted path
        self.goal_pil = None         # PIL image if using Pillow
        self.goal_tk = None          # PhotoImage created from PIL
        self.goal_image_original = None  # Tk PhotoImage if not using PIL
        self.goal_image_scaled = None

        # Build UI
        self._build_ui()
        self._apply_theme(dark=self.dark_mode.get())
        self.after(50, self.auto_load)
        self._schedule_notification_check()
        self.master.bind("<Configure>", self._on_root_resize)

        self._colspec = {
            0: 40,  # Done
            1: 120,  # Status
            2: 70,  # Weight
            3: 0,  # Item (stretch)
            4: 110,  # Due
            5: 80,  # Est. Hrs
            6: 160,  # Tags
            7: 170,  # Actions
        }

    def _apply_colspec(self, frame):
        for i in range(8):
            if i == 3:
                frame.grid_columnconfigure(i, weight=1, minsize=0)
            else:
                frame.grid_columnconfigure(i, weight=0, minsize=self.colspec[i])

    colspec = {0: 40, 1: 120, 2: 70, 3: 0, 4: 110, 5: 80, 6: 160, 7: 170}

    # ---------- Window resize handler ----------
    def _on_root_resize(self, event):
        # Only handle top-level window resize events
        if event.widget is self.master:
            # Re-scale goal image if present
            if getattr(self, "goal_pil", None) is not None or getattr(self, "goal_image_original", None) is not None:
                self._scale_and_apply_goal_image()

    # ---------- UI ----------
    def _build_ui(self):
        self.master.title(APP_TITLE)
        self.master.minsize(1250, 760)

        # Header
        header = ttk.Frame(self)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text=APP_TITLE, font=("TkDefaultFont", 14, "bold")).grid(row=0, column=0, sticky="w")

        right = ttk.Frame(header)
        right.grid(row=0, column=1, sticky="e", padx=(12,0))
        ttk.Checkbutton(right, text="Dark mode", variable=self.dark_mode, command=self._on_toggle_dark).grid(row=0, column=0, padx=4)

        # Goal panel
        goal = ttk.LabelFrame(self, text="Goal")
        goal.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        goal.columnconfigure(0, weight=1)

        self.goal_textbox = tk.Text(goal, height=1, font=("Arial", 32, "bold"))
        self.goal_textbox.grid(row=0, column=0, sticky="ew", padx=8, pady=(8,4))
        self.goal_textbox.bind("<KeyRelease>", lambda e: self._on_goal_text_changed())

        goal_btns = ttk.Frame(goal)
        goal_btns.grid(row=0, column=1, sticky="n", padx=8, pady=(8,4))
        ttk.Button(goal_btns, text="Set Goal Image…", command=self.set_goal_image).grid(row=0, column=0, pady=(0,6))
        ttk.Button(goal_btns, text="Clear Goal Image", command=self.clear_goal_image).grid(row=1, column=0)

        # Goal image preview
        self.goal_image_label = ttk.Label(goal, text="(No goal image)")
        self.goal_image_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0,8))

        # Progress bar + label
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progressbar = ttk.Progressbar(self, orient="horizontal", mode="determinate", variable=self.progress_var, maximum=100)
        self.progressbar.grid(row=2, column=0, sticky="ew", pady=(8, 2))
        self.progress_label = ttk.Label(self, text="0.0%")
        self.progress_label.grid(row=3, column=0, sticky="w", pady=(0, 8))

        # Mode + notify + weekly toggle + tag filter
        bar = ttk.Frame(self)
        bar.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        bar.columnconfigure(1, weight=1)

        ttk.Label(bar, text="Progress mode:").grid(row=0, column=0, padx=(0,6))
        self.combo_mode = ttk.Combobox(bar, values=PROGRESS_MODES, textvariable=self.progress_mode, state="readonly", width=18)
        self.combo_mode.grid(row=0, column=1, padx=(0,12), sticky="w")
        self.combo_mode.bind("<<ComboboxSelected>>", lambda e: self._on_change())

        notify = ttk.Frame(bar)
        notify.grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(notify, text="Notifications", variable=self.notify_enabled).grid(row=0, column=0, padx=(0,6))
        ttk.Label(notify, text="Due within (days):").grid(row=0, column=1, padx=(6,4))
        self.spin_notify_days = ttk.Spinbox(notify, from_=0, to=365, increment=1, textvariable=self.notify_days, width=5)
        self.spin_notify_days.grid(row=0, column=2)

        ttk.Button(bar, text="Toggle Weekly View", command=self.toggle_week_view).grid(row=0, column=3, padx=(12,12))

        ttk.Label(bar, text="Filter by tag:").grid(row=0, column=4, padx=(0,6))
        self.combo_filter = ttk.Combobox(bar, values=["All"], textvariable=self.filter_tag, state="readonly", width=18)
        self.combo_filter.grid(row=0, column=5, padx=(0,0))
        self.combo_filter.bind("<<ComboboxSelected>>", lambda e: self._redraw_visibility())

        # Add item
        add = ttk.LabelFrame(self, text="Add Assignment / Task")
        add.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        add.columnconfigure(1, weight=1)
        ttk.Label(add, text="Name").grid(row=0, column=0, sticky="w", padx=(8,6), pady=6)
        self.entry_name = ttk.Entry(add); self.entry_name.grid(row=0, column=1, sticky="ew", padx=(0,8), pady=6)
        ttk.Label(add, text="Weight").grid(row=0, column=2, sticky="w", padx=(8,6), pady=6)
        self.entry_weight = ttk.Spinbox(add, from_=0.1, to=9999.0, increment=0.1, width=10); self.entry_weight.set("1.0"); self.entry_weight.grid(row=0, column=3, sticky="w", padx=(0,8), pady=6)
        ttk.Label(add, text="Due (YYYY-MM-DD)").grid(row=0, column=4, sticky="w", padx=(8,6), pady=6)
        self.entry_due = ttk.Entry(add, width=14); self.entry_due.grid(row=0, column=5, sticky="w", padx=(0,8), pady=6)
        ttk.Label(add, text="Est. Hours").grid(row=0, column=6, sticky="w", padx=(8,6), pady=6)
        self.entry_hours = ttk.Spinbox(add, from_=0.0, to=9999.0, increment=0.5, width=10); self.entry_hours.set("0.0"); self.entry_hours.grid(row=0, column=7, sticky="w", padx=(0,8), pady=6)
        ttk.Label(add, text="Tags (comma/semicolon)").grid(row=0, column=8, sticky="w", padx=(8,6), pady=6)
        self.entry_tags = ttk.Entry(add, width=20); self.entry_tags.grid(row=0, column=9, sticky="w", padx=(0,8), pady=6)
        ttk.Button(add, text="Add", command=self.add_item_from_inputs).grid(row=0, column=10, sticky="e", padx=(0,8), pady=6)

        # Weekly view
        self.week_panel = ttk.Frame(self); self.week_panel.grid(row=6, column=0, sticky="ew", pady=(0, 8)); self.week_panel.grid_remove()
        self._build_week_view()

        # Table header
        header2 = ttk.Frame(self); header2.grid(row=7, column=0, sticky="ew")
        header2.columnconfigure(3, weight=1)
        ttk.Label(header2, text="Done", width=5, anchor="center").grid(row=0, column=0, padx=4)
        ttk.Label(header2, text="Status", width=14, anchor="center").grid(row=0, column=1, padx=4)
        ttk.Label(header2, text="Weight", width=8, anchor="center").grid(row=0, column=2, padx=4)
        ttk.Label(header2, text="Item", anchor="w").grid(row=0, column=3, sticky="w")
        ttk.Label(header2, text="Due", width=12, anchor="center").grid(row=0, column=4, padx=4)
        ttk.Label(header2, text="Est. Hrs", width=10, anchor="center").grid(row=0, column=5, padx=4)
        ttk.Label(header2, text="Tags", width=16, anchor="center").grid(row=0, column=6, padx=4)
        ttk.Label(header2, text="Actions", width=18, anchor="center").grid(row=0, column=7, padx=4)
        self._apply_colspec(header2)

        # Sort controls
        sort = ttk.Frame(self); sort.grid(row=8, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(sort, text="Sort by:").grid(row=0, column=0, padx=(0,6))
        self.sort_combo = ttk.Combobox(sort, values=["Due Date", "Name", "Weight", "Estimate", "Done", "Status"], textvariable=self.sort_key, width=14, state="readonly")
        self.sort_combo.grid(row=0, column=1, padx=4); self.sort_combo.bind("<<ComboboxSelected>>", lambda e: self.sort_items())
        self.chk_sort_asc = ttk.Checkbutton(sort, text="Ascending", variable=self.sort_ascending, command=self.sort_items); self.chk_sort_asc.grid(row=0, column=2, padx=8)

        # Scroll table
        self.scroll = ScrollableFrame(self); self.scroll.grid(row=9, column=0, sticky="nsew")
        self.grid_rowconfigure(9, weight=1); self.grid_columnconfigure(0, weight=1)

        # Footer (CSV, Save, Load, Clear)
        footer = ttk.Frame(self); footer.grid(row=10, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Checkbutton(footer, text="Autosave", variable=self.autosave_on).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Import CSV (Append)…", command=lambda: self.import_csv(replace=False)).grid(row=0, column=1, padx=4)
        ttk.Button(footer, text="Import CSV (Replace)…", command=lambda: self.import_csv(replace=True)).grid(row=0, column=2, padx=4)
        ttk.Button(footer, text="Export CSV…", command=self.export_csv).grid(row=0, column=3, padx=4)
        ttk.Button(footer, text="Save As…", command=self.save_as).grid(row=0, column=4, padx=4)
        ttk.Button(footer, text="Load…", command=self.load_from_file).grid(row=0, column=5, padx=4)
        ttk.Button(footer, text="Clear All", command=self.clear_all).grid(row=0, column=6, padx=4)

        # Notification banner
        self.banner = ttk.Label(self, text="", anchor="w"); self.banner.grid(row=11, column=0, sticky="ew", pady=(8,0)); self.banner.grid_remove()

        self.pack(fill="both", expand=True)

        # Shortcuts
        for w in (self.entry_name, self.entry_weight, self.entry_due, self.entry_hours, self.entry_tags):
            w.bind("<Return>", lambda e: self.add_item_from_inputs())

    # ---------- Theme ----------
    def _apply_theme(self, dark=True):
        style = ttk.Style(self.master)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        if dark:
            bg = "#101214";
            fg = "#EAEAEA";
            sub = "#1C1F25";
            accent = "#2A2F39";
            pbar_fg = "#2A7BFF"
            sel_bg = "#2F6FEB";
            sel_fg = "#FFFFFF"
            border = "#2B2F36"
        else:
            bg = "#F7F7F7";
            fg = "#1A1A1A";
            sub = "#FFFFFF";
            accent = "#E0E0E0";
            pbar_fg = "#3A7BFF"
            sel_bg = "#D6E4FF";
            sel_fg = "#000000"
            border = "#C7CBD1"

        # Tk window bg
        self.master.configure(bg=bg)

        # Base widget palette
        style.configure(".", background=sub, foreground=fg)
        style.configure("TFrame", background=sub)
        style.configure("TLabelframe", background=sub, foreground=fg)
        style.configure("TLabelframe.Label", background=sub, foreground=fg)
        style.configure("TLabel", background=sub, foreground=fg)
        style.configure("TCheckbutton", background=sub, foreground=fg)
        style.configure("TButton", background=sub, foreground=fg)
        style.configure("TEntry", fieldbackground=sub, foreground=fg, bordercolor=border)
        style.configure("TSpinbox", fieldbackground=sub, foreground=fg, arrowsize=14, bordercolor=border)
        style.configure("Horizontal.TProgressbar", troughcolor=accent, background=pbar_fg)

        # Combobox field + arrow + listbox in dark mode
        style.configure("TCombobox",
                        fieldbackground=sub, foreground=fg,
                        background=sub, arrowcolor=fg,
                        bordercolor=border, lightcolor=border, darkcolor=border)
        style.map("TCombobox",
                  fieldbackground=[("disabled", sub), ("readonly", sub), ("!disabled", sub)],
                  foreground=[("disabled", fg), ("readonly", fg), ("!disabled", fg)],
                  arrowcolor=[("disabled", fg), ("readonly", fg), ("!disabled", fg)])

        # Dropdown listbox colors
        self.master.option_add("*TCombobox*Listbox.background", sub)
        self.master.option_add("*TCombobox*Listbox.foreground", fg)
        self.master.option_add("*TCombobox*Listbox.selectBackground", sel_bg)
        self.master.option_add("*TCombobox*Listbox.selectForeground", sel_fg)
        self.master.option_add("*TCombobox*Listbox.highlightColor", border)
        self.master.option_add("*TCombobox*Listbox.highlightBackground", border)
        self.master.option_add("*TCombobox*Listbox.borderWidth", 0)

        # Repaint week view in the new palette
        self._refresh_week_view()

    def _on_toggle_dark(self):
        self._apply_theme(dark=self.dark_mode.get())
        self._on_change()

    # ---------- Goal handling ----------
    def _on_goal_text_changed(self):
        try:
            self.goal_text = self.goal_textbox.get("1.0", "end-1c")
            if self.autosave_on.get():
                self.auto_save()
        except Exception:
            pass

    def set_goal_image(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Image Files", "*.png;*.gif;*.jpg;*.jpeg"),
                ("PNG", "*.png"),
                ("GIF", "*.gif"),
                ("JPEG", "*.jpg;*.jpeg"),
                ("All Files", "*.*"),
            ],
            title="Choose Goal Image…",
        )
        if not path:
            return

        if PIL_OK:
            try:
                img = Image.open(path).convert("RGBA")
            except Exception as e:
                messagebox.showerror("Failed to load image", f"Could not load image:\n{e}")
                return
            self.goal_image_path = path
            self.goal_pil = img
            self.goal_image_original = None
            self._scale_and_apply_goal_image()
        else:
            try:
                img = tk.PhotoImage(file=path)  # PNG/GIF only
            except Exception as e:
                messagebox.showerror("Failed to load image",
                                     f"Could not load image:\n{e}\n\nTip: install Pillow to load JPGs.")
                return
            self.goal_image_path = path
            self.goal_image_original = img
            self.goal_pil = None
            self._scale_and_apply_goal_image()

    def clear_goal_image(self):
        self.goal_image_path = None
        self.goal_pil = None
        self.goal_tk = None
        self.goal_image_original = None
        self.goal_image_scaled = None
        self.goal_image_label.configure(image="", text="(No goal image)")
        self.goal_image_label.image = None

    def _scale_and_apply_goal_image(self):
        panel_w = max(self.master.winfo_width() - 300, 200)

        if PIL_OK and getattr(self, "goal_pil", None) is not None:
            try:
                iw, ih = self.goal_pil.size
                scale = min(panel_w / iw, 1.0)
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                resized = self.goal_pil.resize((nw, nh), Image.LANCZOS)
                self.goal_tk = ImageTk.PhotoImage(resized)
                self.goal_image_label.configure(image=self.goal_tk, text="")
                self.goal_image_label.image = self.goal_tk  # pin
            except Exception as e:
                messagebox.showerror("Goal Image Error", f"Could not scale goal image:\n{e}")
            return

        img = self.goal_image_original
        if not img:
            self.goal_image_label.configure(image="", text="(No goal image)")
            self.goal_image_label.image = None
            return

        try:
            iw, ih = img.width(), img.height()
            scale = max(0.1, min(panel_w / iw, 1.0))
            if scale >= 1.0:
                z = max(1, int(round(scale))); z = min(z, 5)
                img2 = img.zoom(z, z)
            else:
                ss = max(1, int(round(1.0 / scale))); ss = min(ss, 64)
                img2 = img.subsample(ss, ss)
            self.goal_image_scaled = img2
            self.goal_image_label.configure(image=self.goal_image_scaled, text="")
            self.goal_image_label.image = self.goal_image_scaled  # pin
        except Exception as e:
            messagebox.showerror("Goal Image Error", f"Could not scale goal image:\n{e}")

    # ---------- Items ----------
    def add_item_from_inputs(self):
        name = self.entry_name.get().strip()
        if not name: messagebox.showwarning("Missing Name", "Please enter an item name."); return
        try: weight = float(self.entry_weight.get())
        except ValueError: messagebox.showwarning("Invalid Weight", "Weight must be a number."); return
        if weight <= 0: messagebox.showwarning("Invalid Weight", "Weight must be greater than 0."); return
        due_s = self.entry_due.get().strip(); due = parse_date(due_s)
        if due_s and not due: messagebox.showwarning("Invalid Date", "Due date must be YYYY-MM-DD."); return
        try: hours = float(self.entry_hours.get())
        except ValueError: messagebox.showwarning("Invalid Hours", "Estimated hours must be a number."); return
        if hours < 0: messagebox.showwarning("Invalid Hours", "Estimated hours cannot be negative."); return
        tags_s = self.entry_tags.get().strip()
        tags = normalize_tags(tags_s)
        self.add_item(name=name, weight=weight, done=False, due=due, est_hours=hours, status="Not started", tags=tags)
        # reset
        self.entry_name.delete(0, tk.END); self.entry_weight.set("1.0"); self.entry_due.delete(0, tk.END)
        self.entry_hours.set("0.0"); self.entry_tags.delete(0, tk.END); self.entry_name.focus_set()

    def add_item(self, name, weight, done=False, due=None, est_hours=0.0, status="Not started", tags=None):
        if tags is None: tags = []
        row = ttk.Frame(self.scroll.inner, padding=(0, 2))
        self._apply_colspec(row)
        row.columnconfigure(3, weight=1)

        var_done = tk.BooleanVar(value=done or (status == "Done"))
        var_weight = tk.DoubleVar(value=weight)
        var_hours = tk.DoubleVar(value=float(est_hours))
        var_due_str = tk.StringVar(value=(due.strftime(DATE_FMT) if isinstance(due, date) else ""))
        var_status = tk.StringVar(value=status if status in STATUS_OPTIONS else "Not started")
        var_tags = tk.StringVar(value=", ".join(tags))

        chk = ttk.Checkbutton(row, variable=var_done, command=lambda: self._sync_status_from_checkbox(var_done, var_status))
        chk.grid(row=0, column=0, padx=4)

        cmb_status = ttk.Combobox(row, values=STATUS_OPTIONS, textvariable=var_status, width=14, state="readonly")
        cmb_status.grid(row=0, column=1, padx=4); cmb_status.bind("<<ComboboxSelected>>", lambda e: self._sync_checkbox_from_status(var_status, var_done))

        spn_weight = ttk.Spinbox(row, from_=0.1, to=9999.0, increment=0.1, textvariable=var_weight, width=8); spn_weight.grid(row=0, column=2, padx=4)
        lbl_name = ttk.Label(row, text=name, anchor="w"); lbl_name.grid(row=0, column=3, sticky="w")
        ent_due = ttk.Entry(row, textvariable=var_due_str, width=12); ent_due.grid(row=0, column=4, padx=4)
        spn_hours = ttk.Spinbox(row, from_=0.0, to=9999.0, increment=0.5, textvariable=var_hours, width=10); spn_hours.grid(row=0, column=5, padx=4)
        ent_tags = ttk.Entry(row, textvariable=var_tags, width=22); ent_tags.grid(row=0, column=6, padx=4)

        btns = ttk.Frame(row); btns.grid(row=0, column=7, padx=4)
        ttk.Button(btns, text="Rename", width=8, command=lambda: self.rename_item(lbl_name)).grid(row=0, column=0, padx=2)
        ttk.Button(btns, text="Delete", width=8, command=lambda: self.delete_item(row)).grid(row=0, column=1, padx=2)

        row.pack(fill="x", expand=True)

        item = {
            "row": row,
            "name_label": lbl_name,
            "var_done": var_done,
            "var_weight": var_weight,
            "var_due_str": var_due_str,
            "var_hours": var_hours,
            "var_status": var_status,
            "var_tags": var_tags,
        }
        self.items.append(item)

        for v in (var_weight, var_hours, var_due_str, var_status, var_tags):
            v.trace_add("write", lambda *a: self._on_change())

        self._update_filter_options()
        self._on_change()

    def _sync_status_from_checkbox(self, var_done, var_status):
        if var_done.get():
            var_status.set("Done")
        else:
            if var_status.get() == "Done":
                var_status.set("Not started")
        self._on_change()

    def _sync_checkbox_from_status(self, var_status, var_done):
        var_done.set(var_status.get() == "Done")
        self._on_change()

    def delete_item(self, row_frame):
        for i, it in enumerate(self.items):
            if it["row"] == row_frame:
                it["row"].destroy(); self.items.pop(i); break
        self._update_filter_options()
        self._on_change()

    def rename_item(self, label_widget):
        current = label_widget.cget("text")
        new = simple_prompt(self.master, "Rename Item", "New name:", current)
        if new is not None:
            new = new.strip()
            if new:
                label_widget.config(text=new); self._on_change()

    def clear_all(self):
        if messagebox.askyesno("Clear All", "Delete all items? This cannot be undone."):
            for it in self.items: it["row"].destroy()
            self.items.clear(); self._update_filter_options(); self._on_change()

    # ---------- Progress & Sorting ----------
    def _compute_weighted(self):
        total = done = 0.0
        for it in self.items:
            try: w = float(it["var_weight"].get())
            except tk.TclError: w = 0.0
            if w < 0: w = 0.0
            total += w
            if it["var_done"].get(): done += w
        pct = 0.0 if total <= 0 else (done/total)*100.0
        return pct, done, total, "weight"

    def _compute_unweighted(self):
        visible_items = [it for it in self.items if self._is_visible_by_tag(it)]
        n = len(visible_items)
        done = sum(1 for it in visible_items if it["var_done"].get())
        pct = 0.0 if n == 0 else (done/n)*100.0
        return pct, float(done), float(n), "items"

    def _compute_hours_weighted(self):
        total = done = 0.0
        for it in self.items:
            if not self._is_visible_by_tag(it):
                continue
            try: hrs = float(it["var_hours"].get())
            except tk.TclError: hrs = 0.0
            if hrs < 0: hrs = 0.0
            total += hrs
            if it["var_done"].get(): done += hrs
        pct = 0.0 if total <= 0 else (done/total)*100.0
        return pct, done, total, "hrs"

    def compute_progress(self):
        total_h = rem_h = 0.0
        nearest_due = None
        for it in self.items:
            if not self._is_visible_by_tag(it):
                continue
            try: h = float(it["var_hours"].get())
            except tk.TclError: h = 0.0
            if h < 0: h = 0.0
            total_h += h
            if not it["var_done"].get(): rem_h += h
            d = parse_date(it["var_due_str"].get())
            if d and ((nearest_due is None) or (d < nearest_due)): nearest_due = d

        mode = self.progress_mode.get()
        if mode == "Unweighted": pct, d, t, unit = self._compute_unweighted()
        elif mode == "Hours-weighted": pct, d, t, unit = self._compute_hours_weighted()
        else: pct, d, t, unit = self._compute_weighted()
        return pct, d, t, unit, total_h, rem_h, nearest_due

    def _on_change(self):
        pct, d, t, unit, total_h, rem_h, nearest_due = self.compute_progress()
        self.progress_var.set(pct)
        nearest_txt = nearest_due.strftime(DATE_FMT) if nearest_due else "—"
        self.progress_label.config(text=f"{pct:.1f}% ({d:.1f} / {t:.1f} {unit}) | Hours: {total_h:.1f} total / {rem_h:.1f} remaining | Nearest due: {nearest_txt} | Mode: {self.progress_mode.get()}")
        self.sort_items(refresh_only=True)
        self._refresh_week_view()
        self._redraw_visibility()
        if self.autosave_on.get(): self.auto_save()

    def sort_items(self, refresh_only=False):
        key = self.sort_key.get(); asc = self.sort_ascending.get()
        rows = self.items[:]
        def key_fn(it):
            if key == "Name": return it["name_label"].cget("text").lower()
            elif key == "Weight":
                try: return float(it["var_weight"].get())
                except tk.TclError: return 0.0
            elif key == "Due Date":
                d = parse_date(it["var_due_str"].get()); return (d is None, d or date.max)
            elif key == "Estimate":
                try: return float(it["var_hours"].get())
                except tk.TclError: return 0.0
            elif key == "Done": return it["var_done"].get()
            elif key == "Status": return STATUS_OPTIONS.index(it["var_status"].get()) if it["var_status"].get() in STATUS_OPTIONS else 0
            return 0
        rows.sort(key=key_fn, reverse=not asc)
        for it in rows: it["row"].pack_forget()
        for it in rows: it["row"].pack(fill="x", expand=True)
        self.items = rows

    # ---------- Tag Filter ----------
    def _is_visible_by_tag(self, it):
        sel = self.filter_tag.get()
        if sel == "All": return True
        tags = normalize_tags(it["var_tags"].get())
        return sel in tags

    def _update_filter_options(self):
        tags = set()
        for it in self.items:
            for t in normalize_tags(it["var_tags"].get()):
                tags.add(t)
        options = ["All"] + sorted(tags, key=lambda s: s.lower())
        self.combo_filter.configure(values=options)
        if self.filter_tag.get() not in options:
            self.filter_tag.set("All")

    def _redraw_visibility(self):
        for it in self.items:
            visible = self._is_visible_by_tag(it)
            if visible:
                it["row"].pack(fill="x", expand=True)
            else:
                it["row"].pack_forget()

    # ---------- Weekly View ----------
    def _build_week_view(self):
        self.week_header = ttk.Frame(self.week_panel); self.week_header.grid(row=0, column=0, sticky="ew")
        self.week_cols = []
        for i in range(7):
            col = ttk.Frame(self.week_panel, padding=4)
            col.grid(row=1, column=i, sticky="nsew")
            self.week_panel.grid_columnconfigure(i, weight=1)
            self.week_cols.append(col)
        self._refresh_week_view()

    def toggle_week_view(self):
        if self.week_panel.winfo_viewable():
            self.week_panel.grid_remove()
        else:
            self.week_panel.grid()
            self._refresh_week_view()

    def _clear_week_cols(self):
        for col in self.week_cols:
            for child in col.winfo_children():
                child.destroy()

    def _refresh_week_view(self):
        if not self.week_panel.winfo_viewable():
            return
        for child in self.week_header.winfo_children():
            child.destroy()
        today = date.today()
        for i in range(7):
            d = today + timedelta(days=i)
            ttk.Label(self.week_header, text=d.strftime("%a\n" + DATE_FMT)).grid(row=0, column=i, padx=4, sticky="nsew")
            self.week_panel.grid_columnconfigure(i, weight=1)
        self._clear_week_cols()
        for it in self.items:
            if it["var_done"].get(): continue
            if not self._is_visible_by_tag(it): continue
            d = parse_date(it["var_due_str"].get())
            if not d: continue
            delta = (d - today).days
            if 0 <= delta <= 6:
                name = it["name_label"].cget("text")
                status = it["var_status"].get()
                tags_s = it["var_tags"].get()
                badge = self._urgency_badge(delta)
                text = f"{name}\n[{status}] {badge}"
                if tags_s:
                    text += f"\n#{' #'.join(normalize_tags(tags_s))}"
                ttk.Label(self.week_cols[delta], text=text, anchor="w", justify="left").pack(fill="x", padx=4, pady=2)
        for child in self.week_panel.grid_slaves(row=2):
            child.destroy()
        legend = ttk.Label(self.week_panel, text="Legend: 🔥 today | ⚠ tomorrow | ⏳ next 2–3 days | • later in week | ☑ done hidden | filter applies here")
        legend.grid(row=2, column=0, columnspan=7, sticky="w", padx=4, pady=(6,0))

    def _urgency_badge(self, days_until):
        if days_until < 0: return "⏰ overdue"
        if days_until == 0: return "🔥 today"
        if days_until == 1: return "⚠ tomorrow"
        if days_until <= 3: return "⏳ soon"
        return "• later"

    # ---------- Notifications ----------
    def _schedule_notification_check(self):
        self.after(self.notify_interval_sec * 1000, self._check_notifications)

    def _check_notifications(self):
        try:
            if not self.notify_enabled.get():
                self._schedule_notification_check(); return
            today = date.today()
            horizon = today + timedelta(days=int(self.notify_days.get()))
            due_list = []; overdue_list = []
            for it in self.items:
                if it["var_done"].get(): continue
                if not self._is_visible_by_tag(it): continue
                name = it["name_label"].cget("text")
                d = parse_date(it["var_due_str"].get())
                if not d: continue
                if d < today and name not in self._already_notified:
                    overdue_list.append((name, d))
                elif today <= d <= horizon and name not in self._already_notified:
                    due_list.append((name, d))
            msgs = []
            if overdue_list:
                over_s = ", ".join([f"{n} ({dd.strftime(DATE_FMT)})" for n, dd in overdue_list])
                msgs.append(f"Overdue: {over_s}")
            if due_list:
                due_s = ", ".join([f"{n} ({dd.strftime(DATE_FMT)})" for n, dd in due_list])
                msgs.append(f"Due soon: {due_s}")
            if msgs:
                self._show_banner(" | ".join(msgs))
                try: messagebox.showwarning("Deadlines", "\n".join(msgs))
                except Exception: pass
                if winsound:
                    try: winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                    except Exception: pass
                for (n, _) in overdue_list + due_list: self._already_notified.add(n)
            else:
                self._hide_banner()
        finally:
            self._schedule_notification_check()

    def _show_banner(self, text):
        self.banner.config(text="⚠ " + text); self.banner.grid()
    def _hide_banner(self):
        self.banner.grid_remove()

    # ---------- CSV Import/Export ----------
    def import_csv(self, replace=False):
        path = filedialog.askopenfilename(
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title=("Import CSV (Replace)…" if replace else "Import CSV (Append)…"),
        )
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                headers = [h.strip().lower() for h in (reader.fieldnames or [])]
                required = {"name"}
                if not required.issubset(set(headers)):
                    messagebox.showerror("Invalid CSV", "CSV must, at minimum, include the 'name' column.")
                    return
                if replace:
                    self.clear_all()
                added = 0
                for row in reader:
                    name = (row.get("name") or "").strip()
                    if not name:
                        continue
                    done_str = (row.get("done") or "0").strip()
                    done = done_str in ("1", "true", "True", "yes", "YES")
                    try:
                        weight = float(row.get("weight") or 1.0)
                    except Exception:
                        weight = 1.0
                    due = parse_date(row.get("due"))
                    try:
                        est = float(row.get("est_hours") or 0.0)
                    except Exception:
                        est = 0.0
                    status = row.get("status") or ("Done" if done else "Not started")
                    tags = normalize_tags(row.get("tags") or "")
                    self.add_item(name=name, weight=weight, done=done, due=due, est_hours=est, status=status, tags=tags)
                    added += 1
            messagebox.showinfo("Imported", f"Added {added} item(s) from CSV.")
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not import CSV:\n{e}")

    def export_csv(self):
        if not self.items:
            messagebox.showinfo("Nothing to Export", "No items to export."); return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            title="Export CSV…",
        )
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["name", "done", "weight", "due", "est_hours", "status", "tags"])
                for it in self.items:
                    writer.writerow([
                        it["name_label"].cget("text"),
                        "1" if it["var_done"].get() else "0",
                        f"{float(it['var_weight'].get()):.2f}",
                        it["var_due_str"].get(),
                        f"{float(it['var_hours'].get()):.2f}",
                        it["var_status"].get(),
                        it["var_tags"].get(),
                    ])
            messagebox.showinfo("Exported", f"CSV exported to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not export CSV:\n{e}")

    # ---------- Persistence ----------
    def to_dict(self):
        data = {
            "settings": {
                "dark_mode": bool(self.dark_mode.get()),
                "sort_key": self.sort_key.get(),
                "sort_ascending": bool(self.sort_ascending.get()),
                "progress_mode": self.progress_mode.get(),
                "notify_enabled": bool(self.notify_enabled.get()),
                "notify_days": int(self.notify_days.get()),
                "filter_tag": self.filter_tag.get(),
                "goal_text": self.goal_text,
                "goal_image_path": self.goal_image_path or "",
            },
            "items": []
        }
        for it in self.items:
            data["items"].append({
                "name": it["name_label"].cget("text"),
                "done": bool(it["var_done"].get()),
                "weight": float(it["var_weight"].get() if it["var_weight"].get() else 0.0),
                "due": it["var_due_str"].get(),
                "est_hours": float(it["var_hours"].get() if it["var_hours"].get() else 0.0),
                "status": it["var_status"].get(),
                "tags": it["var_tags"].get(),
            })
        return data

    def from_dict(self, data):
        # Clear items first
        for it in self.items:
            it["row"].destroy()
        self.items.clear()
        self._already_notified.clear()

        settings = data.get("settings", {})
        self.dark_mode.set(bool(settings.get("dark_mode", True)))
        self._apply_theme(dark=self.dark_mode.get())
        self.sort_key.set(settings.get("sort_key", "Due Date"))
        self.sort_ascending.set(bool(settings.get("sort_ascending", True)))
        self.progress_mode.set(settings.get("progress_mode", PROGRESS_MODES[0]))
        self.notify_enabled.set(bool(settings.get("notify_enabled", True)))
        self.notify_days.set(int(settings.get("notify_days", 3)))
        self.filter_tag.set(settings.get("filter_tag", "All"))
        # Goal restore
        self.goal_text = settings.get("goal_text", "")
        self.goal_textbox.delete("1.0", "end")
        if self.goal_text:
            self.goal_textbox.insert("1.0", self.goal_text)

        gp = settings.get("goal_image_path", "")
        if gp and os.path.exists(gp):
            try:
                if PIL_OK:
                    self.goal_pil = Image.open(gp).convert("RGBA")
                    self.goal_image_path = gp
                    self.goal_image_original = None
                else:
                    self.goal_image_original = tk.PhotoImage(file=gp)  # PNG/GIF
                    self.goal_pil = None
                    self.goal_image_path = gp
                self._scale_and_apply_goal_image()
            except Exception:
                self.clear_goal_image()
        else:
            self.clear_goal_image()

        for entry in data.get("items", []):
            name = entry.get("name", "Untitled")
            try: weight = float(entry.get("weight", 1.0))
            except Exception: weight = 1.0
            done = bool(entry.get("done", False))
            due_s = entry.get("due", "")
            due = parse_date(due_s)
            try: est = float(entry.get("est_hours", 0.0))
            except Exception: est = 0.0
            status = entry.get("status", "Done" if done else "Not started")
            tags = normalize_tags(entry.get("tags", ""))
            self.add_item(name, weight, done=done, due=due, est_hours=est, status=status, tags=tags)

        self._update_filter_options()
        self.sort_items()
        self._on_change()

    def auto_save(self):
        try:
            with open(AUTOSAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except Exception as e:
            print("Autosave failed:", e, file=sys.stderr)

    def auto_load(self):
        if os.path.exists(AUTOSAVE_FILE):
            try:
                with open(AUTOSAVE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.from_dict(data)
            except Exception as e:
                messagebox.showwarning("Load Failed", f"Could not load autosave file:\n{e}")

    def save_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Save Progress As…",
        )
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            messagebox.showinfo("Saved", f"Progress saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Save Failed", f"Could not save file:\n{e}")

    # ---------- Load from JSON (manual) ----------
    def load_from_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
            title="Load Progress…",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.from_dict(data)
            messagebox.showinfo("Loaded", f"Loaded progress from:\n{path}")
        except Exception as e:
            messagebox.showerror("Load Failed", f"Could not load file:\n{e}")


def simple_prompt(root, title, prompt, initial_value=""):
    win = tk.Toplevel(root); win.title(title); win.transient(root); win.grab_set(); win.resizable(False, False)
    ttk.Label(win, text=prompt).grid(row=0, column=0, padx=12, pady=(12, 4), sticky="w")
    var = tk.StringVar(value=initial_value)
    ent = ttk.Entry(win, textvariable=var, width=40); ent.grid(row=1, column=0, padx=12, pady=4, sticky="ew"); ent.focus_set()
    btns = ttk.Frame(win); btns.grid(row=2, column=0, padx=12, pady=(8, 12), sticky="e")
    ok = ttk.Button(btns, text="OK", command=lambda: win.destroy()); ok.grid(row=0, column=0)
    cancel_pressed = {"flag": False}
    def on_cancel(): cancel_pressed["flag"] = True; win.destroy()
    ttk.Button(btns, text="Cancel", command=on_cancel).grid(row=0, column=1, padx=(6,0))
    win.bind("<Return>", lambda e: win.destroy()); win.bind("<Escape>", lambda e: on_cancel())
    root.wait_window(win)
    if cancel_pressed["flag"]: return None
    return var.get()


def main():
    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.2)
    except Exception:
        pass
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    app = ProgressTracker(root)
    app.mainloop()


if __name__ == "__main__":
    main()
