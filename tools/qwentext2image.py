#第二版，文生图，文本进度提示
from collections.abc import Generator
from typing import Any
from http import HTTPStatus
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath
import requests
from dashscope import ImageSynthesis
import dashscope
import os
import time

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class Qwentext2imageTool(Tool):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 预创建复用的 session，提高连接效率
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        
        query = tool_parameters.get("query")
        api_key = tool_parameters.get("key")
        
        if not query:
            yield self.create_text_message("错误：请提供文生图描述")
            return
            
        if not api_key:
            yield self.create_text_message("错误：请提供千问 API Key")
            return
        
        try:
            # 记录整体开始时间
            total_start_time = time.time()
            yield self.create_text_message(f"🚀 开始处理请求，描述：{query}\n")
            yield self.create_text_message(f"⏰ 请求开始时间：{time.strftime('%H:%M:%S', time.localtime(total_start_time))}\n")
            
            # 检查输入内容长度和字符
            yield self.create_text_message(f"📝 输入检查 - 描述长度：{len(query)}字符\n")
            if len(query) > 500:
                yield self.create_text_message("⚠️ 警告：描述过长，可能影响生成效果\n")
            
            # 设置 dashscope 的 API Key
            dashscope.api_key = api_key
            
            # 记录任务创建开始时间
            task_create_start = time.time()
            yield self.create_text_message("📤 正在创建图片生成任务...\n")
            
            # 创建异步任务 - 添加更多参数用于调试
            rsp = ImageSynthesis.async_call(
                model="qwen-image",
                prompt=query,
                n=1,
                size='1328*1328'
            )
            
            task_create_end = time.time()
            task_create_time = task_create_end - task_create_start
            yield self.create_text_message(f"✅ 任务创建完成，耗时：{task_create_time:.2f}秒")
            
            # 输出任务ID用于调试
            if hasattr(rsp, 'output') and hasattr(rsp.output, 'task_id'):
                yield self.create_text_message(f"🆔 任务ID已生成\n")
            
            if rsp.status_code != HTTPStatus.OK:
                yield self.create_text_message(
                    f"❌ 创建任务失败 - 状态码: {rsp.status_code}, 错误码: {rsp.code}, 错误信息: {rsp.message}\n"
                )
                return
            
            # 记录等待开始时间
            wait_start_time = time.time()
            yield self.create_text_message("⏳ 任务已创建，开始等待生成完成...\n")
            
            # 优化：使用智能轮询间隔
            max_wait_time = 120  # 减少到2分钟
            check_interval = 2  # 从2秒开始检查
            last_status_message_time = 0
            check_count = 0
            
            while time.time() - wait_start_time < max_wait_time:
                check_count += 1
                # 记录状态检查开始时间
                check_start = time.time()
                
                # 检查任务状态
                status = ImageSynthesis.fetch(rsp)
                
                check_end = time.time()
                check_time = check_end - check_start
                
                if status.status_code == HTTPStatus.OK:
                    task_status = status.output.task_status
                    
                    if task_status == 'SUCCEEDED':
                        wait_end_time = time.time()
                        wait_total_time = wait_end_time - wait_start_time
                        yield self.create_text_message(f"🎉 图片生成完成！等待总耗时：{wait_total_time:.2f}秒，共检查{check_count}次\n")
                        
                        # 记录下载开始时间
                        download_start = time.time()
                        yield self.create_text_message("📥 开始下载图片...\n")
                        
                        # 优化：直接从 status 获取结果，避免额外的 wait 调用
                        if hasattr(status.output, 'results') and status.output.results:
                            results = status.output.results
                            yield self.create_text_message("✅ 从状态检查结果中直接获取图片URL\n")
                        else:
                            # 备用方案：使用 wait 方法
                            yield self.create_text_message("🔄 使用wait方法获取结果...\n")
                            final_rsp = ImageSynthesis.wait(rsp)
                            if final_rsp.status_code == HTTPStatus.OK:
                                results = final_rsp.output.results
                                yield self.create_text_message("✅ 通过wait方法成功获取图片URL\n")
                            else:
                                yield self.create_text_message("❌ 获取生成结果失败\n")
                                return
                        
                        # 下载图片
                        for result in results:
                            try:
                                img_download_start = time.time()
                                yield self.create_text_message(f"🌐 开始从URL下载图片\n")
                                
                                img_response = self._session.get(
                                    result.url,
                                    timeout=30,
                                    stream=True
                                )
                                
                                img_download_end = time.time()
                                img_download_time = img_download_end - img_download_start
                                
                                if img_response.status_code == 200:
                                    yield self.create_text_message(f"✅ 图片下载成功，耗时：{img_download_time:.2f}秒\n")
                                    
                                    # 记录图片处理开始时间
                                    process_start = time.time()
                                    
                                    # 优化：直接读取内容，无需额外处理
                                    image_content = img_response.content
                                    
                                    # 生成文件名
                                    filename = f"qwen_generated_{hash(query) % 100000}.png"
                                    
                                    process_end = time.time()
                                    process_time = process_end - process_start
                                    
                                    # 计算总耗时
                                    total_end_time = time.time()
                                    total_time = total_end_time - total_start_time
                                    
                                    yield self.create_text_message(f"🔧 图片处理完成，耗时：{process_time:.2f}秒\n")
                                    yield self.create_text_message(f"🏁 整个流程完成！总耗时：{total_time:.2f}秒\n")
                                    yield self.create_text_message(f"📊 耗时分解 - 任务创建：{task_create_time:.2f}s | 等待生成：{wait_total_time:.2f}s | 下载图片：{img_download_time:.2f}s | 处理：{process_time:.2f}s\n")
                                    
                                    # 返回图片
                                    yield self.create_blob_message(
                                        blob=image_content,
                                        meta={
                                            "mime_type": "image/png",
                                            "filename": filename
                                        }
                                    )
                                    
                                    # 返回成功消息
                                    yield self.create_json_message({
                                        "status": "success",
                                        "message": "图片生成并下载成功",
                                        "prompt": query,
                                        "filename": filename,
                                        "total_time": f"{total_time:.2f}s",
                                        "breakdown": {
                                            "task_creation": f"{task_create_time:.2f}s",
                                            "generation_wait": f"{wait_total_time:.2f}s",
                                            "image_download": f"{img_download_time:.2f}s",
                                            "processing": f"{process_time:.2f}s"
                                        }
                                    })
                                    return
                                else:
                                    yield self.create_text_message(f"❌ 图片下载失败，状态码：{img_response.status_code}，耗时：{img_download_time:.2f}秒\n")
                                    return
                                    
                            except requests.exceptions.RequestException as e:
                                yield self.create_text_message(f"❌ 图片下载异常：{str(e)}\n")
                                return
                            
                    elif task_status == 'FAILED':
                        wait_time = time.time() - wait_start_time
                        yield self.create_text_message(f"❌ 图片生成失败，等待了{wait_time:.2f}秒\n")
                        return
                        
                    elif task_status in ['PENDING', 'RUNNING']:
                        # 优化：减少状态更新频率，避免过多消息
                        current_time = time.time()
                        elapsed = current_time - wait_start_time
                        
                        if current_time - last_status_message_time > 10:  # 每10秒更新一次状态
                            yield self.create_text_message(f"⏳ 生成中...（状态：{task_status}，已用时{elapsed:.1f}秒，第{check_count}次检查，本次检查耗时{check_time:.3f}秒）\n")
                            last_status_message_time = current_time
                        
                        time.sleep(check_interval)
                        
                        # 优化：渐进式增加检查间隔，避免过于频繁的API调用
                        if check_interval < 5:
                            check_interval += 0.5
                        continue
                    else:
                        yield self.create_text_message(f"❓ 未知任务状态：{task_status}，检查耗时：{check_time:.3f}秒\n")
                        return
                else:
                    yield self.create_text_message(
                        f"❌ 获取任务状态失败 - 状态码: {status.status_code}, 错误码: {status.code}, 错误信息: {status.message}，检查耗时：{check_time:.3f}秒\n"
                    )
                    return
            
            # 如果超时了
            timeout_time = time.time() - total_start_time
            yield self.create_text_message(f"⏰ 任务执行超时，总耗时：{timeout_time:.2f}秒，共检查{check_count}次，请稍后重试\n")
            
        except Exception as e:
            error_time = time.time() - total_start_time
            yield self.create_text_message(f"❌ 调用失败，错误信息：{str(e)}，失败前耗时：{error_time:.2f}秒\n")
        finally:
            # 清理 API Key
            dashscope.api_key = None