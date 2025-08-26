#第二版，实现了图片编辑
from collections.abc import Generator
from typing import Any
from http import HTTPStatus
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath
import requests
from dashscope import MultiModalConversation
import dashscope
import os
import time
import base64
import mimetypes

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

class QwenimageeditTool(Tool):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # 预创建复用的 session，提高连接效率
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def _encode_image_blob(self, image_blob: bytes, file_extension: str = None) -> str:
        """将图片二进制数据编码为base64格式"""
        # 根据文件扩展名确定MIME类型
        if file_extension:
            if file_extension.lower() in ['.jpg', '.jpeg']:
                mime_type = 'image/jpeg'
            elif file_extension.lower() in ['.png']:
                mime_type = 'image/png'
            elif file_extension.lower() in ['.gif']:
                mime_type = 'image/gif'
            elif file_extension.lower() in ['.webp']:
                mime_type = 'image/webp'
            else:
                mime_type = 'image/jpeg'  # 默认为jpeg
        else:
            mime_type = 'image/jpeg'  # 默认为jpeg
        
        # 将二进制数据编码为base64
        encoded_string = base64.b64encode(image_blob).decode('utf-8')
        return f"data:{mime_type};base64,{encoded_string}"
    
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage]:
        
        query = tool_parameters.get("query")
        api_key = tool_parameters.get("key")
        image = tool_parameters.get("image")
        
        if not query:
            yield self.create_text_message("错误：请提供图片修改描述")
            return
            
        if not api_key:
            yield self.create_text_message("错误：请提供千问 API Key")
            return
        
        if not image:
            yield self.create_text_message("错误：请上传需要编辑的图片")
            return
        
        try:
            # 记录整体开始时间
            total_start_time = time.time()
            yield self.create_text_message(f"🚀 开始处理图片编辑请求，描述：{query}\n")
            yield self.create_text_message(f"⏰ 请求开始时间：{time.strftime('%H:%M:%S', time.localtime(total_start_time))}\n")
            
            # 检查输入内容长度和字符
            yield self.create_text_message(f"📝 输入检查 - 描述长度：{len(query)}字符\n")
            if len(query) > 500:
                yield self.create_text_message("⚠️ 警告：描述过长，可能影响编辑效果\n")
            
            # 处理图片文件
            yield self.create_text_message("🖼️ 开始处理上传的图片...\n")
            
            # 从Dify文件对象获取图片数据
            if image.blob:
                # 如果有二进制数据，直接使用
                image_base64 = self._encode_image_blob(image.blob, image.extension if hasattr(image, 'extension') else None)
                yield self.create_text_message("✅ 成功从上传文件获取图片数据\n")
            elif hasattr(image, 'url') and image.url:
                # 如果只有URL，需要下载图片
                yield self.create_text_message("🌐 从URL下载图片...\n")
                try:
                    img_response = self._session.get(image.url, timeout=30)
                    if img_response.status_code == 200:
                        image_base64 = self._encode_image_blob(img_response.content, image.extension if hasattr(image, 'extension') else None)
                        yield self.create_text_message("✅ 成功从URL下载图片\n")
                    else:
                        yield self.create_text_message(f"❌ 图片下载失败，状态码：{img_response.status_code}\n")
                        return
                except Exception as e:
                    yield self.create_text_message(f"❌ 图片下载异常：{str(e)}\n")
                    return
            else:
                yield self.create_text_message("❌ 无法获取图片数据\n")
                return
            
            # 设置 dashscope 的 API Key
            dashscope.api_key = api_key
            
            # 记录API调用开始时间
            api_call_start = time.time()
            yield self.create_text_message("📤 正在调用千问图片编辑API...\n")
            
            # 构建消息格式
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"image": image_base64},
                        {"text": query}
                    ]
                }
            ]
            
            # 调用千问图片编辑API
            response = MultiModalConversation.call(
                api_key=api_key,
                model="qwen-image-edit",
                messages=messages,
                result_format='message',
                stream=False,
                watermark=False,
                negative_prompt=""
            )
            
            api_call_end = time.time()
            api_call_time = api_call_end - api_call_start
            yield self.create_text_message(f"✅ API调用完成，耗时：{api_call_time:.2f}秒\n")
            
            if response.status_code == 200:
                yield self.create_text_message("🎉 图片编辑成功！\n")
                
                # 获取编辑后的图片URL
                if hasattr(response.output, 'choices') and response.output.choices:
                    content = response.output.choices[0].message.content
                    
                    # 查找图片URL
                    image_url = None
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and 'image' in item:
                                image_url = item['image']
                                break
                    elif isinstance(content, str):
                        # 如果content是字符串，可能直接包含URL
                        if content.startswith('http'):
                            image_url = content
                    
                    if image_url:
                        # 记录下载开始时间
                        download_start = time.time()
                        yield self.create_text_message("📥 开始下载编辑后的图片...\n")
                        
                        try:
                            img_response = self._session.get(
                                image_url,
                                timeout=30,
                                stream=True
                            )
                            
                            download_end = time.time()
                            download_time = download_end - download_start
                            
                            if img_response.status_code == 200:
                                yield self.create_text_message(f"✅ 图片下载成功，耗时：{download_time:.2f}秒\n")
                                
                                # 记录图片处理开始时间
                                process_start = time.time()
                                
                                # 获取图片内容
                                image_content = img_response.content
                                
                                # 生成文件名
                                filename = f"qwen_edited_{hash(query) % 100000}.png"
                                
                                process_end = time.time()
                                process_time = process_end - process_start
                                
                                # 计算总耗时
                                total_end_time = time.time()
                                total_time = total_end_time - total_start_time
                                
                                yield self.create_text_message(f"🔧 图片处理完成，耗时：{process_time:.2f}秒\n")
                                yield self.create_text_message(f"🏁 整个流程完成！总耗时：{total_time:.2f}秒\n")
                                yield self.create_text_message(f"📊 耗时分解 - API调用：{api_call_time:.2f}s | 下载图片：{download_time:.2f}s | 处理：{process_time:.2f}s\n")
                                
                                # 返回编辑后的图片
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
                                    "message": "图片编辑并下载成功",
                                    "prompt": query,
                                    "filename": filename,
                                    "total_time": f"{total_time:.2f}s",
                                    "breakdown": {
                                        "api_call": f"{api_call_time:.2f}s",
                                        "image_download": f"{download_time:.2f}s",
                                        "processing": f"{process_time:.2f}s"
                                    }
                                })
                                return
                            else:
                                yield self.create_text_message(f"❌ 图片下载失败，状态码：{img_response.status_code}，耗时：{download_time:.2f}秒\n")
                                return
                                
                        except requests.exceptions.RequestException as e:
                            yield self.create_text_message(f"❌ 图片下载异常：{str(e)}\n")
                            return
                    else:
                        yield self.create_text_message("❌ 无法从响应中获取编辑后的图片URL\n")
                        # 输出调试信息
                        yield self.create_text_message(f"📋 响应内容：{str(content)[:200]}...\n")
                        return
                else:
                    yield self.create_text_message("❌ API响应格式异常\n")
                    return
            else:
                yield self.create_text_message(
                    f"❌ 图片编辑失败 - 状态码: {response.status_code}, 错误码: {response.code}, 错误信息: {response.message}\n"
                )
                return
            
        except Exception as e:
            error_time = time.time() - total_start_time
            yield self.create_text_message(f"❌ 调用失败，错误信息：{str(e)}，失败前耗时：{error_time:.2f}秒\n")
        finally:
            # 清理 API Key
            dashscope.api_key = None