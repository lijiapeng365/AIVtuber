import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
import redis.asyncio as redis
from memory_manager import MemoryManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 全局变量
redis_client: Optional[redis.Redis] = None
memory_manager: Optional[MemoryManager] = None
config = {}

def load_config():
    """加载配置文件"""
    global config
    try:
        config_path = Path(__file__).parent / "config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info("Configuration loaded successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return False

class MemoryService:
    def __init__(self):
        self.processing_tasks = {}
        
    async def process_input_task(self, task_data: dict):
        """处理输入任务（来自input-handler）"""
        try:
            task_id = task_data["task_id"]
            task_type = task_data["type"]
            user_id = task_data.get("user_id", "anonymous")
            
            logger.info(f"Processing memory task {task_id}, type: {task_type}")
            self.processing_tasks[task_id] = "processing"
            
            if task_type == "text":
                await self._process_text_input(task_id, task_data, user_id)
            elif task_type == "audio":
                await self._process_audio_input(task_id, task_data, user_id)
            else:
                logger.warning(f"Unknown task type: {task_type}")
                
        except Exception as e:
            logger.error(f"Error processing input task: {e}")
        finally:
            if task_id in self.processing_tasks:
                del self.processing_tasks[task_id]
    
    async def _process_text_input(self, task_id: str, task_data: dict, user_id: str):
        """处理文本输入并存储到记忆"""
        try:
            input_file = task_data["input_file"]
            
            # 读取输入文本
            with open(input_file, "r", encoding="utf-8") as f:
                input_text = f.read().strip()
            
            logger.info(f"Storing user text: {input_text[:50]}...")
            
            # 存储用户消息到记忆
            message_id = await memory_manager.store_message(
                user_id=user_id,
                message_type="text",
                content=input_text,
                source="user",
                require_ai_response=True,
                metadata={"task_id": task_id, "input_file": input_file}
            )
            
            logger.info(f"Stored user message {message_id}")
            self.processing_tasks[task_id] = "completed"
            
        except Exception as e:
            logger.error(f"Error processing text input: {e}")
    
    async def _process_audio_input(self, task_id: str, task_data: dict, user_id: str):
        """处理音频输入并存储到记忆"""
        try:
            input_file = task_data["input_file"]
            
            logger.info(f"Storing user audio: {input_file}")
            
            # 存储音频消息到记忆（实际应该先做语音识别）
            message_id = await memory_manager.store_message(
                user_id=user_id,
                message_type="audio",
                content=f"[Audio file: {input_file}]",
                source="user",
                require_ai_response=True,
                metadata={"task_id": task_id, "input_file": input_file, "audio_file": input_file}
            )
            
            logger.info(f"Stored user audio message {message_id}")
            self.processing_tasks[task_id] = "completed"
            
        except Exception as e:
            logger.error(f"Error processing audio input: {e}")
    
    async def store_ai_response(self, user_id: str, response_text: str, 
                               original_message_id: str, audio_file: Optional[str] = None):
        """存储AI回复到记忆"""
        try:
            metadata = {"original_message_id": original_message_id}
            if audio_file:
                metadata["audio_file"] = audio_file
            
            message_id = await memory_manager.store_message(
                user_id=user_id,
                message_type="text" if not audio_file else "audio",
                content=response_text,
                source="ai",
                require_ai_response=False,  # AI回复不触发新的AI处理
                metadata=metadata
            )
            
            logger.info(f"Stored AI response {message_id}")
            return message_id
            
        except Exception as e:
            logger.error(f"Error storing AI response: {e}")
            return None

class TaskProcessor:
    def __init__(self):
        self.memory_service = MemoryService()
        
    async def process_task(self, task_data: dict):
        """处理任务"""
        await self.memory_service.process_input_task(task_data)

class ResponseListener:
    """监听AI模块的响应并存储到记忆"""
    def __init__(self):
        self.memory_service = MemoryService()
        
    async def listen_ai_responses(self):
        """监听AI响应频道"""
        if not redis_client:
            logger.error("Redis client not available")
            return
        
        pubsub = redis_client.pubsub()
        await pubsub.subscribe("ai_responses")
        
        logger.info("Started listening for AI responses")
        
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    response_data = json.loads(message["data"])
                    await self._handle_ai_response(response_data)
                except Exception as e:
                    logger.error(f"Error handling AI response: {e}")
    
    async def _handle_ai_response(self, response_data: dict):
        """处理AI响应数据"""
        try:
            user_id = response_data.get("user_id", "anonymous")
            response_text = response_data.get("text", "")
            original_message_id = response_data.get("original_message_id", "")
            audio_file = response_data.get("audio_file")
            
            await self.memory_service.store_ai_response(
                user_id, response_text, original_message_id, audio_file
            )
            
        except Exception as e:
            logger.error(f"Error processing AI response data: {e}")

async def init_redis():
    """初始化Redis连接"""
    global redis_client
    try:
        redis_config = config.get("redis", {})
        redis_client = redis.Redis(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6379),
            decode_responses=True
        )
        await redis_client.ping()
        logger.info("Connected to Redis")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        redis_client = None

async def init_memory_manager():
    """初始化记忆管理器"""
    global memory_manager
    if redis_client:
        memory_manager = MemoryManager(redis_client, config)
        logger.info("Memory manager initialized")
    else:
        logger.error("Cannot initialize memory manager without Redis")

async def cleanup():
    """清理资源"""
    if redis_client:
        await redis_client.close()
    logger.info("Memory service shutdown")

async def input_queue_listener():
    """监听输入队列"""
    if not redis_client:
        logger.error("Redis client not available")
        return
        
    processor = TaskProcessor()
    queue_name = config.get("redis", {}).get("input_queue", "user_input_queue")
    
    logger.info(f"Starting input queue listener for {queue_name}")
    
    while True:
        try:
            result = await redis_client.brpop(queue_name, timeout=1)
            
            if result:
                queue_name_result, message = result
                task_data = json.loads(message)
                
                logger.info(f"Received input task: {task_data}")
                
                # 异步处理任务
                asyncio.create_task(processor.process_task(task_data))
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in queue message: {e}")
        except Exception as e:
            logger.error(f"Error in input queue listener: {e}")
            await asyncio.sleep(1)

async def memory_cleanup_scheduler():
    """定期清理过期记忆"""
    if not memory_manager:
        return
        
    cleanup_interval = config.get("memory", {}).get("cleanup_interval_hours", 6) * 3600
    
    while True:
        try:
            await asyncio.sleep(cleanup_interval)
            await memory_manager.cleanup_old_memories()
        except Exception as e:
            logger.error(f"Error in memory cleanup: {e}")

async def main():
    """主函数"""
    logger.info("Starting Memory Service...")
    
    # 加载配置
    if not load_config():
        logger.error("Failed to load configuration, exiting")
        return
    
    # 初始化Redis
    await init_redis()
    
    if not redis_client:
        logger.error("Cannot start without Redis connection")
        return
    
    # 初始化记忆管理器
    await init_memory_manager()
    
    if not memory_manager:
        logger.error("Cannot start without memory manager")
        return
    
    try:
        # 启动各种监听器和调度器
        await asyncio.gather(
            input_queue_listener(),
            ResponseListener().listen_ai_responses(),
            memory_cleanup_scheduler()
        )
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await cleanup()

if __name__ == "__main__":
    asyncio.run(main())