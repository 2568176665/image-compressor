import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import os
import subprocess
import glob
import threading
import concurrent.futures
import logging

class ImageCompressorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("图片压缩工具")
        self.root.geometry("650x500")
        self.root.resizable(False, False)

        # 配置网格布局 - 只用4列
        self.root.grid_columnconfigure(1, weight=1)  # 第2列（输入框列）可扩展
        self.root.grid_rowconfigure(9, weight=1)     # 第10行（日志）可扩展

        # 配置日志
        logging.basicConfig(filename='compression.log', level=logging.INFO, 
                          format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')
        
        # 输入路径
        tk.Label(root, text="输入路径:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.input_entry = tk.Entry(root)
        self.input_entry.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.input_entry.insert(0, os.path.join(".", "input"))
        tk.Button(root, text="选择文件", command=self.select_file, width=10).grid(row=0, column=2, padx=2, pady=5)
        tk.Button(root, text="选择文件夹", command=self.select_folder, width=12).grid(row=0, column=3, padx=2, pady=5)

        # 输出路径
        tk.Label(root, text="输出路径:").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.output_entry = tk.Entry(root)
        self.output_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        self.output_entry.insert(0, os.path.join(".", "output"))
        tk.Button(root, text="选择文件夹", command=self.select_output_folder, width=12).grid(
            row=1, column=2, columnspan=2, padx=2, pady=5)

        # 目标大小
        tk.Label(root, text="目标大小 (KB):").grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.size_entry = tk.Entry(root, width=15)
        self.size_entry.grid(row=2, column=1, padx=10, pady=5, sticky="w")
        self.size_entry.insert(0, "100")

        # Resize 功能
        tk.Label(root, text="Resize:").grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.resize_var = tk.StringVar(value="不使用")
        resize_combo = ttk.Combobox(root, textvariable=self.resize_var, 
                                   values=["不使用", "640x480", "800x600", "1024x768", "1280x720", "1920x1080"], 
                                   state="readonly", width=15)
        resize_combo.grid(row=3, column=1, padx=10, pady=5, sticky="w")
        resize_combo.bind("<<ComboboxSelected>>", self.on_resize_preset_selected)
        
        # 宽高输入框架
        size_frame = tk.Frame(root)
        size_frame.grid(row=3, column=2, columnspan=2, padx=5, pady=5, sticky="w")
        tk.Label(size_frame, text="宽:").pack(side="left")
        self.width_entry = tk.Entry(size_frame, width=8)
        self.width_entry.pack(side="left", padx=(2,10))
        tk.Label(size_frame, text="高:").pack(side="left")
        self.height_entry = tk.Entry(size_frame, width=8)
        self.height_entry.pack(side="left", padx=2)

        # 输出格式
        tk.Label(root, text="输出格式:").grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.format_var = tk.StringVar(value="jpg")
        format_combo = ttk.Combobox(root, textvariable=self.format_var,
                                   values=["jpg", "png", "webp"], state="readonly", width=15)
        format_combo.grid(row=4, column=1, padx=10, pady=5, sticky="w")

        # 最大线程数
        tk.Label(root, text="最大线程数:").grid(row=4, column=2, padx=10, pady=5, sticky="w")
        self.max_workers_entry = tk.Entry(root, width=10)
        self.max_workers_entry.grid(row=4, column=3, padx=10, pady=5, sticky="w")
        self.max_workers_entry.insert(0, "0")

        # 压缩按钮
        self.compress_button = tk.Button(root, text="开始压缩", command=self.start_compression, 
                                        bg="#4CAF50", fg="white", height=2)
        self.compress_button.grid(row=5, column=0, columnspan=4, pady=15, sticky="ew", padx=10)

        # 进度条
        self.progress = ttk.Progressbar(root, orient="horizontal", mode="determinate")
        self.progress.grid(row=6, column=0, columnspan=4, padx=10, pady=5, sticky="ew")

        # 状态标签
        self.status_label = tk.Label(root, text="准备就绪")
        self.status_label.grid(row=7, column=0, columnspan=4, padx=10, pady=5)

        # 日志输出
        tk.Label(root, text="日志:").grid(row=8, column=0, padx=10, pady=5, sticky="nw")
        self.log_text = tk.Text(root, height=8, state='disabled', wrap='word')
        self.log_text.grid(row=9, column=0, columnspan=4, padx=10, pady=5, sticky="nsew")

    def get_resize_value(self):
        width = self.width_entry.get().strip()
        height = self.height_entry.get().strip()
        if width and height:
            return f"{width}x{height}"
        return None

    def on_resize_preset_selected(self, event):
        preset = self.resize_var.get()
        if preset != "不使用":
            width, height = preset.split('x')
            self.width_entry.delete(0, tk.END)
            self.width_entry.insert(0, width)
            self.height_entry.delete(0, tk.END)
            self.height_entry.insert(0, height)
        else:
            self.width_entry.delete(0, tk.END)
            self.height_entry.delete(0, tk.END)

    def select_file(self):
        file_path = filedialog.askopenfilename(filetypes=[("Image files", "*.jpg *.jpeg *.png *.webp")])
        if file_path:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, file_path)

    def select_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.input_entry.delete(0, tk.END)
            self.input_entry.insert(0, folder_path)

    def select_output_folder(self):
        folder_path = filedialog.askdirectory()
        if folder_path:
            self.output_entry.delete(0, tk.END)
            self.output_entry.insert(0, folder_path)

    def start_compression(self):
        logging.info("开始压缩任务")
        self.append_log("开始压缩任务")
        input_path = self.input_entry.get()
        output_path = self.output_entry.get()
        target_size_kb = self.size_entry.get()
        output_format = self.format_var.get()
        resize_value = self.get_resize_value()

        # 获取 max_workers
        max_workers_str = self.max_workers_entry.get().strip()
        if max_workers_str and max_workers_str != "0":
            try:
                max_workers = int(max_workers_str)
            except ValueError:
                max_workers = os.cpu_count()
        else:
            max_workers = os.cpu_count()

        if not input_path or not output_path or not target_size_kb:
            messagebox.showerror("错误", "请填写所有字段")
            return

        try:
            target_size = int(target_size_kb) * 1024
        except ValueError:
            messagebox.showerror("错误", "目标大小必须是数字")
            return

        # 智能获取文件列表
        image_files = []
        if os.path.isfile(input_path):
            image_files = [input_path]
        elif os.path.isdir(input_path):
            for ext in ('*.jpg', '*.jpeg', '*.png', '*.webp', '*.JPG', '*.JPEG', '*.PNG', '*.WEBP'):
                image_files.extend(glob.glob(os.path.join(input_path, ext)))
            image_files = list(set(image_files))  # 去除重复项
        else:
            messagebox.showerror("错误", "输入路径无效")
            return

        if not image_files:
            messagebox.showerror("错误", "未找到图片文件")
            return

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        # 初始化界面状态
        self.progress["maximum"] = len(image_files)
        self.progress["value"] = 0
        self.status_label.config(text="正在分析并压缩...")
        self.compress_button.config(state="disabled")

        # 开启后台线程进行管理
        threading.Thread(target=self.run_tasks, args=(image_files, output_path, target_size, output_format, resize_value, max_workers)).start()

    def run_tasks(self, image_files, output_path, target_size, output_format, resize_value, max_workers):
        logging.info(f"开始处理 {len(image_files)} 个文件")
        completed = 0
        total = len(image_files)

        # 使用指定的 max_workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            futures = [executor.submit(self.compress_single, img, output_path, target_size, output_format, resize_value) for img in image_files]
            
            # 获取结果
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                try:
                    result = future.result()
                    # 在主线程更新UI
                    self.root.after(0, self.update_status, completed, total, result)
                except Exception as e:
                    logging.error(f"任务错误: {e}")

        self.root.after(0, self.finish_compression)

    def update_status(self, completed, total, msg):
        self.progress["value"] = completed
        self.status_label.config(text=f"进度: {completed}/{total} - {msg}")

    def append_log(self, message):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + '\n')
        self.log_text.config(state='disabled')
        self.log_text.see(tk.END)

    def finish_compression(self):
        logging.info("所有图片处理完成")
        self.append_log("所有图片处理完成")
        self.status_label.config(text="所有图片处理完成")
        self.compress_button.config(state="normal")
        messagebox.showinfo("完成", "压缩任务已完成！")

    def compress_single(self, input_file, output_dir, target_size, output_format, resize_value):
        logging.info(f"开始压缩文件: {input_file}")
        base_name = os.path.splitext(os.path.basename(input_file))[0]
        output_file = os.path.join(output_dir, f"{base_name}.{output_format}")
        magick_path = "ImageMagick\\magick.exe" # 确保此路径存在

        # 确保 magick 存在
        if not os.path.exists(magick_path):
            # 尝试直接调用全局命令，防止用户没放文件夹
            magick_path = "magick"

        # --- 策略 1: 针对 JPG 的极速智能压缩 ---
        if output_format in ["jpg", "jpeg"]:
            # 使用 -define jpeg:extent 可以让 ImageMagick 自动计算最佳参数
            target_kb = target_size // 1024
            cmd = [magick_path, input_file]
            if resize_value:
                cmd.extend(["-resize", resize_value])
            cmd.extend(["-strip", "-define", f"jpeg:extent={target_kb}kb", output_file])
            try:
                subprocess.run(cmd, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                if os.path.exists(output_file):
                    actual_size = os.path.getsize(output_file)
                    if actual_size <= target_size * 1.00:  # 允许0%误差
                        return f"成功: {base_name}"
                    # 否则删除文件,进入二分查找
                    os.remove(output_file)
            except Exception as e:
                logging.error(f"JPG 极速压缩失败: {input_file}, 错误: {e}")
                pass # 失败则进入下面的通用逻辑



        # --- 策略 2: 通用二分查找法 (Binary Search) ---
        # 相比原先的线性查找(20次)，二分法只需约 5-6 次即可找到最佳点
        # 智能初始质量估算
        original_size = os.path.getsize(input_file)
        ratio = target_size / original_size
        if ratio >= 0.8:
            current_quality = 95
        elif ratio >= 0.5:
            current_quality = 80
        elif ratio >= 0.2:
            current_quality = 60
        else:
            current_quality = 40

        low, high = 0, 100
        best_quality = 0

        for _ in range(6): # 最多尝试6次，足够覆盖精度
            cmd = [magick_path, input_file]
            if resize_value:
                cmd.extend(["-resize", resize_value])
            cmd.append("-strip")

            if output_format == "png":
                # 使用压缩级别而非颜色数
                compression = max(0, min(9, int(9 * (100 - current_quality) / 100)))
                cmd.extend(["-quality", str(compression)])
            else:
                cmd.extend(["-quality", str(current_quality)])

            cmd.append(output_file)

            try:
                subprocess.run(cmd, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                size = os.path.getsize(output_file)

                if size <= target_size:
                    best_quality = current_quality
                    # 达标了，尝试提高质量看能不能更好
                    low = current_quality + 1
                else:
                    # 超标了，降低质量
                    high = current_quality - 1

                current_quality = (low + high) // 2
                if low > high:
                    break
            except Exception as e:
                logging.error(f"质量调整失败: {input_file}, 错误: {e}")
                break

        if best_quality == 0:
            # 无法达到目标大小
            warning_msg = f"警告: {base_name} - 质量已降至最低，无法达到目标大小"
            logging.warning(warning_msg)
            self.root.after(0, self.append_log, warning_msg)
            return f"失败: {base_name} (无法达到目标)"
        else:
            # 使用计算出的 best_quality 重新生成一遍文件，确保最终文件合格
            cmd = [magick_path, input_file]
            if resize_value:
                cmd.extend(["-resize", resize_value])
            cmd.append("-strip")

            if output_format == "png":
                # 使用压缩级别而非颜色数
                compression = max(0, min(9, int(9 * (100 - best_quality) / 100)))
                cmd.extend(["-quality", str(compression)])
            else:
                cmd.extend(["-quality", str(best_quality)])

            cmd.append(output_file)

            try:
                subprocess.run(cmd, capture_output=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            except Exception as e:
                logging.error(f"最终生成失败: {input_file}, 错误: {e}")
                return f"失败: {base_name} (最终生成失败)"

            result = f"完成: {base_name}"
            logging.info(result)
            return result

if __name__ == "__main__":
    root = tk.Tk()
    app = ImageCompressorApp(root)
    root.mainloop()