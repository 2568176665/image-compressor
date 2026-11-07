from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .compression import (
    SUPPORTED_FORMATS,
    CompressionResult,
    CompressionService,
    expand_input_paths,
    normalize_format,
    resolve_max_workers,
)
from .config import (
    DEFAULT_CONFIG,
    OUTPUT_MODE_CUSTOM,
    OUTPUT_MODE_KEYS,
    OUTPUT_MODE_LABELS,
    ConfigStore,
    normalize_output_mode,
    output_name_suffix,
    resolve_output_dir,
)
from .runtime import CodecRuntimeManager, EnsureResult

try:  # 可选依赖：缺失时只是不支持拖拽，其余功能不受影响。
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # pragma: no cover - 依赖缺失时走降级分支
    DND_FILES = None  # type: ignore[assignment]
    TkinterDnD = None  # type: ignore[assignment]

DND_SUPPORTED = TkinterDnD is not None and DND_FILES is not None
FILE_DIALOG_TYPES = [
    ("图片文件", "*.jpg *.jpeg *.png *.webp *.avif"),
    ("所有文件", "*.*"),
]


def create_root() -> tk.Tk:
    """创建根窗口；装了 tkinterdnd2 时同时获得拖拽能力。"""
    if DND_SUPPORTED:
        return TkinterDnD.Tk()  # type: ignore[union-attr]
    return tk.Tk()


class ImageCompressorApp:
    def __init__(self, root: tk.Tk, *, config_store: ConfigStore, runtime_manager: CodecRuntimeManager):
        self.root = root
        self.root.title("图片压缩工具")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.config_store = config_store
        self.runtime_manager = runtime_manager
        self.runtime_result: EnsureResult | None = None
        self.service = CompressionService(encoder_paths=None)
        self.is_compressing = False
        self.input_paths: list[str] = []

        self.overwrite_var = tk.BooleanVar(value=False)
        default_mode = normalize_output_mode(DEFAULT_CONFIG["output_mode"])
        self.output_mode_var = tk.StringVar(value=OUTPUT_MODE_LABELS[default_mode])
        self.custom_output_dir_var = tk.StringVar()
        self.format_var = tk.StringVar(value=str(DEFAULT_CONFIG["format"]))

        self.build_ui()
        self.bind_events()
        self.load_config()
        self.update_custom_output_state()
        self.fit_window()
        self.start_runtime_check()

    def build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=(10, 8))
        main.grid(row=0, column=0, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(0, weight=3)
        main.grid_rowconfigure(5, weight=2)

        input_group = ttk.LabelFrame(main, text="输入图片", padding=(8, 6))
        input_group.grid(row=0, column=0, sticky="nsew")
        input_group.grid_columnconfigure(0, weight=1)
        input_group.grid_rowconfigure(0, weight=1)

        self.input_listbox = tk.Listbox(
            input_group,
            selectmode=tk.EXTENDED,
            exportselection=False,
            height=6,
            width=52,
            activestyle="none",
        )
        self.input_listbox.grid(row=0, column=0, sticky="nsew")
        input_scroll = ttk.Scrollbar(input_group, orient="vertical", command=self.input_listbox.yview)
        input_scroll.grid(row=0, column=1, sticky="ns")
        self.input_listbox.config(yscrollcommand=input_scroll.set)

        input_actions = ttk.Frame(input_group)
        input_actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        input_actions.grid_columnconfigure(0, weight=1)

        hint_text = "支持拖拽图片或文件夹到列表" if DND_SUPPORTED else "点击“添加”选择图片或文件夹"
        ttk.Label(input_actions, text=hint_text, foreground="#777777").grid(row=0, column=0, sticky="w")

        input_buttons = ttk.Frame(input_actions)
        input_buttons.grid(row=0, column=1, sticky="e")

        # 用普通 tk.Button + 弹出菜单，保证与“移除选中”“清空”外观完全一致。
        self.add_button = tk.Button(input_buttons, text="添加 ▾", command=self.show_add_menu, width=9)
        self.add_button.grid(row=0, column=0, padx=(0, 4))

        self.add_menu = tk.Menu(self.add_button, tearoff=False)
        self.add_menu.add_command(label="选择图片（可多选）", command=self.select_images)
        self.add_menu.add_command(label="选择文件夹", command=self.select_input_folder)

        self.remove_button = tk.Button(
            input_buttons, text="移除选中", command=self.remove_selected, width=9
        )
        self.remove_button.grid(row=0, column=1, padx=(0, 4))

        self.clear_button = tk.Button(input_buttons, text="清空", command=self.clear_inputs, width=6)
        self.clear_button.grid(row=0, column=2)

        output_row = ttk.Frame(main)
        output_row.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        output_row.grid_columnconfigure(2, weight=1)

        ttk.Label(output_row, text="输出方式:").grid(row=0, column=0, padx=(0, 6), sticky="e")
        self.output_mode_combo = ttk.Combobox(
            output_row,
            textvariable=self.output_mode_var,
            values=list(OUTPUT_MODE_LABELS.values()),
            state="readonly",
            width=20,
        )
        self.output_mode_combo.grid(row=0, column=1, sticky="w")

        self.custom_output_entry = tk.Entry(output_row, textvariable=self.custom_output_dir_var)
        self.custom_output_entry.grid(row=0, column=2, padx=(8, 6), sticky="ew")

        self.custom_output_button = tk.Button(
            output_row,
            text="选择…",
            command=self.select_custom_output_dir,
            width=8,
        )
        self.custom_output_button.grid(row=0, column=3, sticky="e")

        params = ttk.LabelFrame(main, text="压缩参数", padding=(8, 6))
        params.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        params.grid_columnconfigure(1, weight=1)
        params.grid_columnconfigure(3, weight=1)

        ttk.Label(params, text="目标大小 (KB):").grid(row=0, column=0, padx=(0, 6), pady=2, sticky="e")
        self.size_entry = tk.Entry(params, width=10)
        self.size_entry.grid(row=0, column=1, pady=2, sticky="ew")

        ttk.Label(params, text="Resize (宽x高/百分比%):").grid(
            row=0, column=2, padx=(12, 6), pady=2, sticky="e"
        )
        self.resize_entry = tk.Entry(params, width=10)
        self.resize_entry.grid(row=0, column=3, pady=2, sticky="ew")

        ttk.Label(params, text="输出格式:").grid(row=1, column=0, padx=(0, 6), pady=2, sticky="e")
        ttk.Combobox(
            params,
            textvariable=self.format_var,
            values=list(SUPPORTED_FORMATS),
            state="readonly",
            width=10,
        ).grid(row=1, column=1, pady=2, sticky="ew")

        ttk.Label(params, text="最大线程数:").grid(row=1, column=2, padx=(12, 6), pady=2, sticky="e")
        self.max_workers_entry = tk.Entry(params, width=10)
        self.max_workers_entry.grid(row=1, column=3, pady=2, sticky="ew")

        ttk.Checkbutton(params, text="覆盖同名输出文件", variable=self.overwrite_var).grid(
            row=2, column=2, columnspan=2, padx=(12, 0), pady=(4, 0), sticky="w"
        )

        action_row = ttk.Frame(main)
        action_row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        action_row.grid_columnconfigure(0, weight=3)
        action_row.grid_columnconfigure(1, weight=1)

        self.compress_button = tk.Button(
            action_row,
            text="开始压缩",
            command=self.start_compression,
            bg="#4CAF50",
            fg="white",
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        self.compress_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), ipady=4)

        self.cancel_button = tk.Button(
            action_row,
            text="取消",
            command=self.cancel_compression,
            bg="#f44336",
            fg="white",
            font=("Microsoft YaHei UI", 10, "bold"),
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(4, 0), ipady=4)

        self.progress = ttk.Progressbar(main, orient="horizontal", mode="determinate")
        self.progress.grid(row=4, column=0, sticky="ew", pady=(8, 0))

        log_group = ttk.LabelFrame(main, text="日志", padding=(8, 6))
        log_group.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        log_group.grid_columnconfigure(0, weight=1)
        log_group.grid_rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_group, height=5, width=52, state="disabled", wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_group, orient="vertical", command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.config(yscrollcommand=log_scroll.set)

    def fit_window(self) -> None:
        """按内容自然尺寸收紧窗口，用户仍可自行放大。"""
        self.root.update_idletasks()
        width = max(600, self.root.winfo_reqwidth())
        height = max(500, self.root.winfo_reqheight())
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)


    def bind_events(self) -> None:
        self.output_mode_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_custom_output_state())
        self.setup_drag_and_drop()

    def setup_drag_and_drop(self) -> None:
        if not DND_SUPPORTED:
            return
        self.input_listbox.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
        self.input_listbox.dnd_bind("<<Drop>>", self.on_drop)  # type: ignore[attr-defined]

    def on_drop(self, event) -> str:
        try:
            dropped_paths = list(self.root.tk.splitlist(event.data))
        except tk.TclError:
            dropped_paths = [str(event.data)]
        self.add_paths(dropped_paths)
        return getattr(event, "action", "copy")

    def current_output_mode(self) -> str:
        return normalize_output_mode(
            OUTPUT_MODE_KEYS.get(self.output_mode_var.get(), DEFAULT_CONFIG["output_mode"])
        )

    def update_custom_output_state(self) -> None:
        is_custom = self.current_output_mode() == OUTPUT_MODE_CUSTOM
        state = "normal" if is_custom else "disabled"
        self.custom_output_entry.config(state=state)
        self.custom_output_button.config(state=state)
        # 非自定义模式下把两个控件收起，避免占宽和干扰视线。
        if is_custom:
            self.custom_output_entry.grid()
            self.custom_output_button.grid()
        else:
            self.custom_output_entry.grid_remove()
            self.custom_output_button.grid_remove()

    def get_resize_value(self) -> str | None:
        value = self.resize_entry.get().strip()
        return value or None

    def show_add_menu(self) -> None:
        x = self.add_button.winfo_rootx()
        y = self.add_button.winfo_rooty() + self.add_button.winfo_height()
        try:
            self.add_menu.tk_popup(x, y)
        finally:
            self.add_menu.grab_release()

    def select_images(self) -> None:
        selected = filedialog.askopenfilenames(title="选择图片", filetypes=FILE_DIALOG_TYPES)
        if selected:
            self.add_paths(list(selected))

    def select_input_folder(self) -> None:
        folder_path = filedialog.askdirectory(title="选择文件夹")
        if folder_path:
            self.add_paths([folder_path])

    def select_custom_output_dir(self) -> None:
        folder_path = filedialog.askdirectory(title="选择输出目录")
        if folder_path:
            self.custom_output_dir_var.set(folder_path)

    def add_paths(self, paths: list[str]) -> None:
        if not paths:
            return

        image_files, invalid_paths = expand_input_paths(paths)
        known = {os.path.normcase(os.path.abspath(item)) for item in self.input_paths}
        added = 0
        for image_file in image_files:
            key = os.path.normcase(os.path.abspath(image_file))
            if key in known:
                continue
            known.add(key)
            self.input_paths.append(image_file)
            added += 1

        self.refresh_input_listbox()

        if added:
            self.append_log(f"已添加 {added} 张图片，当前共 {len(self.input_paths)} 张")
        elif image_files:
            messagebox.showinfo("提示", "所选图片已经在列表里了。")
        elif invalid_paths:
            messagebox.showwarning("提示", "所选路径中没有可用的图片文件。")
        else:
            messagebox.showinfo("提示", "所选文件夹中没有图片文件。")

    def refresh_input_listbox(self) -> None:
        self.input_listbox.delete(0, tk.END)
        for path in self.input_paths:
            self.input_listbox.insert(tk.END, path)

    def remove_selected(self) -> None:
        selection = set(self.input_listbox.curselection())
        if not selection:
            return
        self.input_paths = [path for index, path in enumerate(self.input_paths) if index not in selection]
        self.refresh_input_listbox()

    def clear_inputs(self) -> None:
        if not self.input_paths:
            return
        self.input_paths.clear()
        self.refresh_input_listbox()

    def load_config(self) -> None:
        config = self.config_store.load()
        self.apply_input_paths(config.get("input_paths", DEFAULT_CONFIG["input_paths"]))
        configured_mode = normalize_output_mode(config.get("output_mode", DEFAULT_CONFIG["output_mode"]))
        self.output_mode_var.set(OUTPUT_MODE_LABELS[configured_mode])
        self.custom_output_dir_var.set(str(config.get("custom_output_dir", "") or ""))
        self.overwrite_var.set(bool(config.get("overwrite", DEFAULT_CONFIG["overwrite"])))
        configured_format = normalize_format(str(config.get("format", DEFAULT_CONFIG["format"])))
        self.format_var.set(configured_format if configured_format in SUPPORTED_FORMATS else str(DEFAULT_CONFIG["format"]))

        self.size_entry.delete(0, tk.END)
        self.size_entry.insert(0, str(config.get("target_size_kb", DEFAULT_CONFIG["target_size_kb"])))

        self.max_workers_entry.delete(0, tk.END)
        self.max_workers_entry.insert(0, str(config.get("max_workers", DEFAULT_CONFIG["max_workers"])))

        self.resize_entry.delete(0, tk.END)
        configured_resize = str(config.get("resize", DEFAULT_CONFIG["resize"]))
        self.resize_entry.insert(0, "" if configured_resize == "不使用" else configured_resize)

    def apply_input_paths(self, paths: object) -> None:
        candidates = [str(item).strip() for item in (paths or []) if str(item).strip()]  # type: ignore[union-attr]
        existing = [path for path in candidates if os.path.isfile(path)]
        self.input_paths = existing
        self.refresh_input_listbox()
        missing_count = len(candidates) - len(existing)
        if missing_count > 0:
            self.append_log(f"已跳过 {missing_count} 个不存在的历史路径")

    def save_config(self) -> None:
        self.config_store.save(
            {
                "input_paths": list(self.input_paths),
                "output_mode": self.current_output_mode(),
                "custom_output_dir": self.custom_output_dir_var.get().strip(),
                "target_size_kb": self.size_entry.get(),
                "resize": self.resize_entry.get().strip() or "不使用",
                "format": self.format_var.get(),
                "max_workers": self.max_workers_entry.get(),
                "overwrite": self.overwrite_var.get(),
            }
        )

    def start_runtime_check(self) -> None:
        self.compress_button.config(state="disabled")
        threading.Thread(target=self.run_runtime_check, daemon=True).start()

    def run_runtime_check(self) -> None:
        result = self.runtime_manager.ensure_codecs_ready()
        self.root.after(0, self.finish_runtime_check, result)

    def finish_runtime_check(self, result: EnsureResult) -> None:
        self.runtime_result = result
        if result.ready:
            self.service.set_encoder_paths(result.encoder_paths)
        self.append_log(result.message)
        self.compress_button.config(
            state="normal" if result.ready and not self.is_compressing else "disabled"
        )

    def start_compression(self) -> None:
        if not self.runtime_result or not self.runtime_result.ready or not self.service.encoder_paths:
            messagebox.showwarning("提示", "编码器尚未准备完成，请稍后再试。")
            return

        output_mode = self.current_output_mode()
        custom_output_dir = self.custom_output_dir_var.get().strip()
        if output_mode == OUTPUT_MODE_CUSTOM and not custom_output_dir:
            messagebox.showerror("错误", "请先选择自定义输出目录")
            return

        target_size_kb = self.size_entry.get().strip()
        if not target_size_kb:
            messagebox.showerror("错误", "请填写目标大小")
            return
        try:
            target_size = int(target_size_kb) * 1024
        except ValueError:
            messagebox.showerror("错误", "目标大小必须是数字")
            return
        if target_size <= 0:
            messagebox.showerror("错误", "目标大小必须大于 0")
            return

        missing = [path for path in self.input_paths if not os.path.isfile(path)]
        if missing:
            self.input_paths = [path for path in self.input_paths if os.path.isfile(path)]
            self.refresh_input_listbox()
            self.append_log(f"已移除 {len(missing)} 个不存在的输入文件")

        image_files = list(self.input_paths)
        if not image_files:
            messagebox.showerror("错误", "请先添加图片")
            return

        max_workers = resolve_max_workers(self.max_workers_entry.get())
        self.progress["maximum"] = len(image_files)
        self.progress["value"] = 0
        self.compress_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.is_compressing = True
        summary = f"开始压缩任务（{len(image_files)} 张，输出方式：{OUTPUT_MODE_LABELS[output_mode]}）"
        self.append_log(summary)
        logging.info(summary)

        threading.Thread(
            target=self.run_tasks,
            args=(
                image_files,
                output_mode,
                custom_output_dir,
                target_size,
                self.format_var.get(),
                self.get_resize_value(),
                max_workers,
                self.overwrite_var.get(),
            ),
            daemon=True,
        ).start()

    def run_tasks(
        self,
        image_files: list[str],
        output_mode: str,
        custom_output_dir: str,
        target_size: int,
        output_format: str,
        resize_value: str | None,
        max_workers: int,
        overwrite: bool,
    ) -> None:
        status = "failed"
        try:
            status = self.service.run_batch(
                image_files,
                target_size=target_size,
                output_format=output_format,
                resize_value=resize_value,
                max_workers=max_workers,
                overwrite=overwrite,
                name_suffix=output_name_suffix(output_mode),
                output_dir_resolver=lambda image_file: resolve_output_dir(
                    output_mode, image_file, custom_output_dir
                ),
                progress_callback=self._on_progress,
            )
        except Exception:
            logging.exception("压缩任务异常退出")
            status = "failed"
        finally:
            self.root.after(0, self.finish_compression, status)

    def _on_progress(self, completed: int, total: int, result: CompressionResult) -> None:
        self.root.after(0, self.update_status, completed, total, result.message)

    def update_status(self, completed: int, total: int, message: str) -> None:
        self.progress["value"] = completed
        self.append_log(f"进度: {completed}/{total} - {message}")

    def append_log(self, message: str) -> None:
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state="disabled")
        self.log_text.see(tk.END)
        self.log_text.update_idletasks()

    def finish_compression(self, status: str) -> None:
        self.is_compressing = False
        self.cancel_button.config(state="disabled")
        final_messages = {
            "completed": "所有图片处理完成",
            "cancelled": "压缩任务已取消",
            "failed": "压缩任务已结束，部分文件处理失败",
        }
        message = final_messages.get(status, "压缩任务已结束")
        logging.info(message)
        self.append_log(message)
        if self.runtime_result and self.runtime_result.ready:
            self.compress_button.config(state="normal")
        else:
            self.compress_button.config(state="disabled")

    def cancel_compression(self) -> None:
        if not self.is_compressing:
            return
        self.cancel_button.config(state="disabled")
        self.append_log("正在取消压缩任务...")
        self.service.cancel()

    def on_close(self) -> None:
        if self.is_compressing:
            self.cancel_compression()
            self.root.after(300, self._close_after_cancel)
            return
        self.save_config()
        self.root.destroy()

    def _close_after_cancel(self) -> None:
        if self.is_compressing:
            self.root.after(200, self._close_after_cancel)
            return
        self.save_config()
        self.root.destroy()
