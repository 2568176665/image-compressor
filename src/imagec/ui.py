from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .compression import CompressionService, collect_image_files, resolve_max_workers
from .config import ConfigStore, DEFAULT_CONFIG, derive_output_path
from .runtime import ImageMagickManager, EnsureResult, summarize_runtime_result


class ImageCompressorApp:
    def __init__(self, root: tk.Tk, *, config_store: ConfigStore, runtime_manager: ImageMagickManager):
        self.root = root
        self.root.title("图片压缩工具")
        self.root.geometry("600x440")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.config_store = config_store
        self.runtime_manager = runtime_manager
        self.runtime_result: EnsureResult | None = None
        self.runtime_summary = None
        self.service = CompressionService(magick_path=None)
        self.is_compressing = False

        self.auto_output_var = tk.BooleanVar(value=True)
        self.input_path_var = tk.StringVar(value=DEFAULT_CONFIG["input_path"])
        self.output_path_var = tk.StringVar()
        self.resize_var = tk.StringVar(value=DEFAULT_CONFIG["resize"])
        self.format_var = tk.StringVar(value=DEFAULT_CONFIG["format"])

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
        main_frame.grid_rowconfigure(7, weight=1)

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
        self.auto_output_button = tk.Button(
            output_actions,
            command=self.toggle_auto_output,
            width=button_width,
            relief="flat",
            bd=0,
            fg="white",
            activeforeground="white",
        )
        self.auto_output_button.grid(row=0, column=0, padx=(0, 6))
        self.output_button = tk.Button(
            output_actions,
            text="选择文件夹",
            command=self.select_output_folder,
            width=button_width,
        )
        self.output_button.grid(row=0, column=1)

        tk.Label(main_frame, text="目标大小 (KB):").grid(row=2, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        self.size_entry = tk.Entry(main_frame, width=field_width)
        self.size_entry.grid(row=2, column=1, pady=row_padding, sticky="ew")

        tk.Label(main_frame, text="Resize:").grid(row=2, column=2, padx=(12, 8), pady=row_padding, sticky="e")
        resize_group = tk.Frame(main_frame)
        resize_group.grid(row=2, column=3, pady=row_padding, sticky="ew")
        resize_group.grid_columnconfigure(0, weight=1)

        resize_combo = ttk.Combobox(
            resize_group,
            textvariable=self.resize_var,
            values=["不使用", "640x480", "800x600", "1024x768", "1280x720", "1920x1080"],
            state="readonly",
            width=field_width,
        )
        resize_combo.grid(row=0, column=0, sticky="ew")
        resize_combo.bind("<<ComboboxSelected>>", self.on_resize_preset_selected)

        size_frame = tk.Frame(resize_group)
        size_frame.grid(row=1, column=0, pady=(4, 0), sticky="w")
        tk.Label(size_frame, text="宽").grid(row=0, column=0, sticky="w")
        self.width_entry = tk.Entry(size_frame, width=6)
        self.width_entry.grid(row=0, column=1, padx=(4, 10))
        tk.Label(size_frame, text="高").grid(row=0, column=2, sticky="w")
        self.height_entry = tk.Entry(size_frame, width=6)
        self.height_entry.grid(row=0, column=3, padx=(4, 0))

        tk.Label(main_frame, text="输出格式:").grid(row=3, column=0, padx=(0, 8), pady=row_padding, sticky="e")
        format_combo = ttk.Combobox(
            main_frame,
            textvariable=self.format_var,
            values=["jpg", "png", "webp"],
            state="readonly",
            width=field_width,
        )
        format_combo.grid(row=3, column=1, pady=row_padding, sticky="ew")

        tk.Label(main_frame, text="最大线程数:").grid(row=3, column=2, padx=(12, 8), pady=row_padding, sticky="e")
        self.max_workers_entry = tk.Entry(main_frame, width=field_width)
        self.max_workers_entry.grid(row=3, column=3, pady=row_padding, sticky="ew")

        compress_button_frame = tk.Frame(main_frame)
        compress_button_frame.grid(row=4, column=0, columnspan=4, pady=(10, 8), sticky="ew")
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
        self.progress.grid(row=5, column=0, columnspan=4, pady=(0, 8), sticky="ew")

        tk.Label(main_frame, text="日志:").grid(row=6, column=0, padx=(0, 8), pady=(2, 4), sticky="nw")
        self.log_text = tk.Text(main_frame, height=6, state="disabled", wrap="word")
        self.log_text.grid(row=7, column=0, columnspan=4, sticky="nsew")
        self.refresh_auto_output_button()

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
        self.refresh_auto_output_button()

    def toggle_auto_output(self) -> None:
        self.auto_output_var.set(not self.auto_output_var.get())
        self.update_output_path_mode()

    def refresh_auto_output_button(self) -> None:
        if self.auto_output_var.get():
            self.auto_output_button.config(text="自动输出", bg="#43A047", activebackground="#388E3C")
        else:
            self.auto_output_button.config(text="手动输出", bg="#78909C", activebackground="#607D8B")

    def sync_output_path(self) -> None:
        self.output_path_var.set(derive_output_path(self.input_path_var.get()))

    def get_resize_value(self) -> str | None:
        width = self.width_entry.get().strip()
        height = self.height_entry.get().strip()
        if width and height:
            return f"{width}x{height}"
        return None

    def on_resize_preset_selected(self, _event) -> None:
        preset = self.resize_var.get()
        self.width_entry.delete(0, tk.END)
        self.height_entry.delete(0, tk.END)
        if "x" in preset:
            width, height = preset.split("x")
            self.width_entry.insert(0, width)
            self.height_entry.insert(0, height)

    def select_file(self) -> None:
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
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
        self.format_var.set(config.get("format", DEFAULT_CONFIG["format"]))
        self.resize_var.set(config.get("resize", DEFAULT_CONFIG["resize"]))

        self.size_entry.delete(0, tk.END)
        self.size_entry.insert(0, config.get("target_size_kb", DEFAULT_CONFIG["target_size_kb"]))
        self.width_entry.delete(0, tk.END)
        self.width_entry.insert(0, config.get("resize_width", DEFAULT_CONFIG["resize_width"]))
        self.height_entry.delete(0, tk.END)
        self.height_entry.insert(0, config.get("resize_height", DEFAULT_CONFIG["resize_height"]))
        self.max_workers_entry.delete(0, tk.END)
        self.max_workers_entry.insert(0, config.get("max_workers", DEFAULT_CONFIG["max_workers"]))

    def save_config(self) -> None:
        self.config_store.save(
            {
                "input_path": self.input_path_var.get(),
                "auto_output": self.auto_output_var.get(),
                "output_path": self.output_path_var.get(),
                "target_size_kb": self.size_entry.get(),
                "resize": self.resize_var.get(),
                "resize_width": self.width_entry.get(),
                "resize_height": self.height_entry.get(),
                "format": self.format_var.get(),
                "max_workers": self.max_workers_entry.get(),
            }
        )

    def start_runtime_check(self) -> None:
        self.compress_button.config(state="disabled")
        threading.Thread(target=self.run_runtime_check, daemon=True).start()

    def run_runtime_check(self) -> None:
        result = self.runtime_manager.ensure_imagemagick_ready(status_callback=self.handle_runtime_status)
        self.root.after(0, self.finish_runtime_check, result)

    def handle_runtime_status(self, message: str) -> None:
        logging.info(message)
        self.root.after(0, self.append_log, message)

    def finish_runtime_check(self, result: EnsureResult) -> None:
        self.runtime_result = result
        self.runtime_summary = summarize_runtime_result(result)
        self.service.magick_path = result.magick_path
        self.append_log(self.runtime_summary.message)
        self.compress_button.config(
            state="normal" if self.runtime_summary.can_start and not self.is_compressing else "disabled"
        )

    def start_compression(self) -> None:
        if not self.runtime_summary or not self.runtime_summary.can_start or not self.service.magick_path:
            messagebox.showwarning("提示", "ImageMagick 尚未准备完成，请稍后再试。")
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
            args=(image_files, output_path, target_size, self.format_var.get(), self.get_resize_value(), max_workers),
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
    ) -> None:
        summary = self.service.run_batch(
            image_files,
            output_dir=output_path,
            target_size=target_size,
            output_format=output_format,
            resize_value=resize_value,
            max_workers=max_workers,
            progress_callback=lambda completed, total, result: self.root.after(
                0, self.update_status, completed, total, result.message
            ),
        )
        self.root.after(0, self.finish_compression, summary.status)

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
        if self.runtime_summary and self.runtime_summary.can_start:
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
