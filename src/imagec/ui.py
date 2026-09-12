from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .compression import (
    SUPPORTED_FORMATS,
    DEFAULT_VISUAL_SCORE,
    VISUAL_QUALITY_PRESETS,
    CompressionResult,
    CompressionService,
    collect_image_files,
    normalize_format,
    resolve_max_workers,
)
from .config import ConfigStore, DEFAULT_CONFIG, derive_output_path
from .runtime import CodecRuntimeManager, EnsureResult


class ImageCompressorApp:
    def __init__(self, root: tk.Tk, *, config_store: ConfigStore, runtime_manager: CodecRuntimeManager):
        self.root = root
        self.root.title("图片压缩工具")
        self.root.geometry("600x430")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.config_store = config_store
        self.runtime_manager = runtime_manager
        self.runtime_result: EnsureResult | None = None
        self.service = CompressionService(encoder_paths=None)
        self.is_compressing = False

        self.auto_output_var = tk.BooleanVar(value=True)
        self.input_path_var = tk.StringVar(value=str(DEFAULT_CONFIG["input_path"]))
        self.output_path_var = tk.StringVar()
        self.format_var = tk.StringVar(value=str(DEFAULT_CONFIG["format"]))
        self.visual_quality_var = tk.StringVar(value=str(DEFAULT_CONFIG["visual_quality"]))

        self.build_ui()
        self.bind_events()
        self.load_config()
        self.update_output_path_mode()
        self.start_runtime_check()

    def build_ui(self) -> None:
        main_frame = tk.Frame(self.root, padx=10, pady=8)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.grid_columnconfigure(1, weight=1)
        main_frame.grid_columnconfigure(3, weight=1)
        main_frame.grid_rowconfigure(8, weight=1)

        field_width = 18
        button_width = 10
        row_padding = 4

        tk.Label(main_frame, text="输入路径:").grid(row=0, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        self.input_entry = tk.Entry(main_frame, textvariable=self.input_path_var)
        self.input_entry.grid(row=0, column=1, pady=row_padding, sticky="ew")

        input_actions = tk.Frame(main_frame)
        input_actions.grid(row=0, column=2, columnspan=2, padx=(8, 0), pady=row_padding, sticky="e")
        tk.Button(input_actions, text="选择文件", command=self.select_file, width=button_width).grid(row=0, column=0, padx=(0, 6))
        tk.Button(input_actions, text="选择文件夹", command=self.select_folder, width=button_width).grid(row=0, column=1)

        tk.Label(main_frame, text="输出路径:").grid(row=1, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        self.output_entry = tk.Entry(main_frame, textvariable=self.output_path_var)
        self.output_entry.grid(row=1, column=1, pady=row_padding, sticky="ew")

        output_actions = tk.Frame(main_frame)
        output_actions.grid(row=1, column=2, columnspan=2, padx=(8, 0), pady=row_padding, sticky="e")
        self.auto_output_button = ttk.Checkbutton(
            output_actions,
            text="自动输出",
            variable=self.auto_output_var,
            command=self.update_output_path_mode,
        )
        self.auto_output_button.grid(row=0, column=0, padx=(0, 6))
        self.output_button = tk.Button(
            output_actions,
            text="选择文件夹",
            command=self.select_output_folder,
            width=button_width,
        )
        self.output_button.grid(row=0, column=1)

        tk.Label(main_frame, text="最大大小 (KB):", font=("Segoe UI", 9)).grid(row=2, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        self.size_entry = tk.Entry(main_frame, width=field_width)
        self.size_entry.grid(row=2, column=1, pady=row_padding, sticky="ew")

        tk.Label(main_frame, text="Resize (宽x高/百分比%):", font=("Segoe UI", 9)).grid(row=2, column=2, padx=(12, 8), pady=row_padding, sticky="e")
        resize_frame = tk.Frame(main_frame)
        resize_frame.grid(row=2, column=3, pady=row_padding, sticky="ew")
        resize_frame.grid_columnconfigure(0, weight=1)
        self.resize_entry = tk.Entry(resize_frame, width=field_width)
        self.resize_entry.grid(row=0, column=0, sticky="ew")

        tk.Label(main_frame, text="输出格式:").grid(row=3, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        format_combo = ttk.Combobox(
            main_frame,
            textvariable=self.format_var,
            values=list(SUPPORTED_FORMATS),
            state="readonly",
            width=field_width,
        )
        format_combo.grid(row=3, column=1, pady=row_padding, sticky="ew")

        tk.Label(main_frame, text="最大线程数:").grid(row=3, column=2, padx=(12, 8), pady=row_padding, sticky="e")
        self.max_workers_entry = tk.Entry(main_frame, width=field_width)
        self.max_workers_entry.grid(row=3, column=3, pady=row_padding, sticky="ew")

        tk.Label(main_frame, text="视觉质量:").grid(row=4, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        ttk.Combobox(
            main_frame,
            textvariable=self.visual_quality_var,
            values=list(VISUAL_QUALITY_PRESETS),
            state="readonly",
            width=field_width,
        ).grid(row=4, column=1, pady=row_padding, sticky="ew")

        compress_button_frame = tk.Frame(main_frame)
        compress_button_frame.grid(row=5, column=0, columnspan=4, pady=(10, 8), sticky="ew")
        compress_button_frame.grid_columnconfigure(0, weight=3)
        compress_button_frame.grid_columnconfigure(1, weight=1)

        self.compress_button = tk.Button(
            compress_button_frame,
            text="开始压缩",
            command=self.start_compression,
            bg="#4CAF50",
            fg="white",
            height=2,
        )
        self.compress_button.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.cancel_button = tk.Button(
            compress_button_frame,
            text="取消",
            command=self.cancel_compression,
            bg="#f44336",
            fg="white",
            height=2,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.progress = ttk.Progressbar(main_frame, orient="horizontal", mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=4, pady=(0, 8), sticky="ew")

        tk.Label(main_frame, text="日志:").grid(row=7, column=0, padx=(0, 8), pady=(2, 4), sticky="nw")
        self.log_text = tk.Text(main_frame, height=7, state="disabled", wrap="word")
        self.log_text.grid(row=8, column=0, columnspan=4, sticky="nsew")

    def bind_events(self) -> None:
        self.input_path_var.trace_add("write", self.on_input_path_changed)

    def on_input_path_changed(self, *_args) -> None:
        if self.auto_output_var.get():
            self.sync_output_path()

    def update_output_path_mode(self) -> None:
        if self.auto_output_var.get():
            self.sync_output_path()
            self.output_entry.config(state="disabled")
            self.output_button.config(state="disabled")
        else:
            self.output_entry.config(state="normal")
            self.output_button.config(state="normal")

    def sync_output_path(self) -> None:
        self.output_path_var.set(derive_output_path(self.input_path_var.get()))

    def get_resize_value(self) -> str | None:
        value = self.resize_entry.get().strip()
        return value or None

    def select_file(self) -> None:
        file_path = filedialog.askopenfilename(
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp *.avif")]
        )
        if file_path:
            self.input_path_var.set(file_path)

    def select_folder(self) -> None:
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.input_path_var.set(folder_path)

    def select_output_folder(self) -> None:
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.output_path_var.set(folder_path)

    def load_config(self) -> None:
        config = self.config_store.load()
        self.input_path_var.set(config.get("input_path", DEFAULT_CONFIG["input_path"]))
        self.auto_output_var.set(config.get("auto_output", DEFAULT_CONFIG["auto_output"]))
        self.output_path_var.set(config.get("output_path", DEFAULT_CONFIG["output_path"]))
        configured_format = normalize_format(str(config.get("format", DEFAULT_CONFIG["format"])))
        self.format_var.set(configured_format if configured_format in SUPPORTED_FORMATS else str(DEFAULT_CONFIG["format"]))
        self.resize_entry.delete(0, tk.END)
        configured_resize = str(config.get("resize", DEFAULT_CONFIG["resize"]))
        self.resize_entry.insert(0, "" if configured_resize == "不使用" else configured_resize)

    def save_config(self) -> None:
        self.config_store.save(
            {
                "input_path": self.input_path_var.get(),
                "auto_output": self.auto_output_var.get(),
                "output_path": self.output_path_var.get(),
                "target_size_kb": self.size_entry.get(),
                "resize": self.resize_entry.get().strip() or "不使用",
                "format": self.format_var.get(),
                "visual_quality": self.visual_quality_var.get(),
                "max_workers": self.max_workers_entry.get(),
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
            self.service.set_encoder_paths(result.encoder_paths, result.metric_path)
        self.append_log(result.message)
        self.compress_button.config(
            state="normal" if result.ready and not self.is_compressing else "disabled"
        )

    def start_compression(self) -> None:
        if not self.runtime_result or not self.runtime_result.ready or not self.service.encoder_paths:
            messagebox.showwarning("提示", "编码器尚未准备完成，请稍后再试。")
            return

        input_path = self.input_entry.get().strip()
        output_path = self.output_entry.get().strip()
        target_size_kb = self.size_entry.get().strip()
        if not input_path or not output_path or not target_size_kb:
            messagebox.showerror("错误", "请填写所有字段")
            return

        try:
            target_size = int(target_size_kb) * 1024
        except ValueError:
            messagebox.showerror("错误", "目标大小必须是数字")
            return
        if target_size <= 0:
            messagebox.showerror("错误", "目标大小必须大于 0")
            return

        image_files = collect_image_files(input_path)
        if image_files is None:
            messagebox.showerror("错误", "输入路径无效")
            return
        if not image_files:
            messagebox.showerror("错误", "未找到图片文件")
            return

        max_workers = resolve_max_workers(self.max_workers_entry.get())
        self.progress["maximum"] = len(image_files)
        self.progress["value"] = 0
        self.compress_button.config(state="disabled")
        self.cancel_button.config(state="normal")
        self.is_compressing = True
        self.append_log("开始压缩任务")
        logging.info("开始压缩任务")

        threading.Thread(
            target=self.run_tasks,
            args=(
                image_files,
                output_path,
                target_size,
                self.format_var.get(),
                self.get_resize_value(),
                max_workers,
                VISUAL_QUALITY_PRESETS.get(self.visual_quality_var.get(), DEFAULT_VISUAL_SCORE),
            ),
            daemon=True,
        ).start()

    def run_tasks(
        self,
        image_files: list[str],
        output_path: str,
        target_size: int,
        output_format: str,
        resize_value: str | None,
        max_workers: int,
        min_visual_score: float | None,
    ) -> None:
        status = self.service.run_batch(
            image_files,
            output_dir=output_path,
            target_size=target_size,
            output_format=output_format,
            resize_value=resize_value,
            max_workers=max_workers,
            min_visual_score=min_visual_score,
            progress_callback=self._on_progress,
        )
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
