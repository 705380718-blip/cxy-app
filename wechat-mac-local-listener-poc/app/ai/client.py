from __future__ import annotations

import asyncio
import json
import time
import re
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import ValidationError

from ..work_items import DeliveryError
from .prompts import make_messages, smoke_context
from .schemas import AnalysisResult


class AIError(DeliveryError):
    def __init__(self, code, detail, retryable=False, retry_after=0):
        super().__init__(code,detail,502)
        self.retryable, self.retry_after = retryable, retry_after


class DeepSeekClient:
    def __init__(self, store, database, transport=None, sleep=asyncio.sleep):
        self.store, self.database = store,database
        self.transport, self.sleep = transport,sleep
        self.test_lock = asyncio.Lock()

    def reserve_call(self, config):
        day = datetime.now(timezone(timedelta(hours=8))).date().isoformat()
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT OR IGNORE INTO ai_call_budget(day,calls) VALUES (?,0)',(day,))
            calls = conn.execute('SELECT calls FROM ai_call_budget WHERE day=?',(day,)).fetchone()[0]
            current,_=self.store.snapshot()
            if calls>=min(config.max_calls_per_day,current.max_calls_per_day):
                raise AIError('daily_budget','今日模型请求已达上限，请调整预算或明日重试')
            conn.execute('UPDATE ai_call_budget SET calls=calls+1 WHERE day=?',(day,))

    async def _request(self, client, method, endpoint, config, **kwargs):
        self.reserve_call(config)
        try:
            response = await asyncio.wait_for(client.request(method,endpoint,**kwargs), timeout=config.timeout_seconds)
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise AIError('timeout','模型请求超时',True) from exc
        except httpx.RequestError as exc:
            raise AIError('network','无法连接 DeepSeek，请检查网络',True) from exc
        code = response.status_code
        if code != 200:
            message = {401:('authentication','API Key 无效'),403:('permission','账号无权访问'),402:('balance','账号余额不足'),429:('rate_limit','请求过于频繁'),400:('request_invalid','模型请求参数不被账号支持')}.get(code,('server_error','模型服务暂时不可用') if code>=500 else ('http_error','模型接口拒绝请求'))
            try:
                wait = max(0,min(float(response.headers.get('Retry-After','0')),10))
            except ValueError:
                wait = 0
            # Do not return provider body: it can include user data or echoed credentials.
            raise AIError(*message,retryable=code==429 or code>=500,retry_after=wait)
        try:
            if len(response.content)>2*1024*1024:
                raise ValueError('oversized provider result')
            return response.json()
        except (ValueError,UnicodeError) as exc:
            raise AIError('response_invalid','模型接口响应格式不合法') from exc

    async def _models(self, client, config):
        for attempt in range(3):
            try:
                payload = await self._request(client,'GET','models',config)
                models = {entry['id'] for entry in payload['data']}
                if config.model not in models:
                    raise AIError('model_unavailable','账号未提供当前配置模型，请核对模型 ID')
                return
            except (KeyError,TypeError) as exc:
                raise AIError('response_invalid','模型列表格式不合法') from exc
            except AIError as exc:
                if not exc.retryable or attempt == 2:
                    raise
                await self.sleep(max(exc.retry_after,2**attempt))

    async def _analyze(self, client, config, context, *, max_attempts=3, before_attempt=None, after_attempt=None, corrected=False):
        messages = make_messages(context)
        if len(json.dumps(messages,ensure_ascii=False))>config.max_input_chars:
            raise AIError('input_too_large','上下文超过配置字符上限，请缩小范围')
        message_ids = {m['id'] for m in context['messages']}
        item_ids = {item['id'] for item in context.get('open_items',[])}
        for attempt in range(max_attempts):
            if before_attempt:
                before_attempt()
            started = time.monotonic()
            try:
                payload = await self._request(client,'POST','chat/completions',config,json={
                    'model':config.model,'messages':messages,'stream':False,
                    'thinking':{'type':'disabled'},'response_format':{'type':'json_object'},
                    'max_tokens':config.max_output_tokens,
                })
                try:
                    choice = payload['choices'][0]
                    if choice['finish_reason'] != 'stop':
                        raise AIError('truncated','模型输出未完整结束')
                    content = choice['message']['content']
                    if not isinstance(content,str) or not content.strip():
                        raise AIError('empty_content','模型返回空正文')
                    result = AnalysisResult.model_validate_json(content)
                    result.validate_scope(message_ids,set(context.get('persons',{})),item_ids)
                except (KeyError,IndexError,TypeError,ValueError,ValidationError) as exc:
                    raise AIError('result_invalid','模型 JSON 或消息依据校验未通过') from exc
                metadata = {
                    'requested_model':config.model,
                    'returned_model':self.safe_identifier(payload.get('model')),
                    'request_id':self.safe_identifier(payload.get('id')),
                    'tokens':self.safe_tokens(payload.get('usage',{})),
                    'latency_ms':round((time.monotonic()-started)*1000),
                    'attempts':attempt+1,
                    'finish_reason':'stop',
                }
                if after_attempt: after_attempt(metadata)
                return result, metadata
            except AIError as exc:
                if after_attempt: after_attempt({'latency_ms':round((time.monotonic()-started)*1000),'error_code':exc.code})
                result_error = exc.code in {'result_invalid','truncated','empty_content'}
                if attempt == max_attempts-1 or (not exc.retryable and (not result_error or corrected)):
                    raise
                if result_error:
                    corrected = True
                    # No invalid provider output is stored or injected back into context.
                    messages = [*make_messages(context), {'role':'user','content':'上次 JSON 或依据校验未通过。请重新严格输出 JSON，证据 ID 必须来自输入，所有字段必须遵守示例，不补造信息。'}]
                    if len(json.dumps(messages,ensure_ascii=False))>config.max_input_chars:
                        raise AIError('input_too_large','纠正请求超过字符上限，请缩小范围')
                await self.sleep(max(exc.retry_after,2**attempt) if exc.retryable else 0)

    def safe_identifier(self, value):
        _,key=self.store.snapshot()
        if not isinstance(value,str) or value.startswith('sk-') or (key and key in value):
            return 'unknown'
        return value if re.fullmatch(r'[A-Za-z0-9._:-]{1,100}',value) else 'unknown'

    @staticmethod
    def safe_tokens(usage):
        value=usage.get('total_tokens') if isinstance(usage,dict) else None
        return value if type(value) is int and 0 <= value <= 10000000 else None

    async def analyze_job(self, config, context, **callbacks):
        _,key=self.store.snapshot()
        if not key: raise AIError('key_missing','未配置 API Key')
        async with httpx.AsyncClient(base_url=config.base_url+'/',headers={'Authorization':f'Bearer {key}'},timeout=config.timeout_seconds,transport=self.transport,follow_redirects=False,trust_env=False) as client:
            return await asyncio.wait_for(self._analyze(client,config,context,**callbacks),timeout=210)

    async def connection_test(self):
        if self.test_lock.locked():
            raise DeliveryError('test_running','连通测试正在进行，请等待结果',409)
        async with self.test_lock:
            config,key = self.store.snapshot()
            if not key:
                raise DeliveryError('key_missing','请先保存 DeepSeek API Key',409)
            async def run():
                # Relative endpoints retain an optional /v1 prefix; never follow auth redirects.
                async with httpx.AsyncClient(base_url=config.base_url+'/',headers={'Authorization':f'Bearer {key}'},timeout=config.timeout_seconds,transport=self.transport,follow_redirects=False,trust_env=False) as client:
                    await self._models(client,config)
                    result,metrics = await self._analyze(client,config,smoke_context())
                    return {'status':'ok','sample_kind':'simulated','json_validated':True,'item_count':len(result.items),**metrics}
            try:
                result = await asyncio.wait_for(run(),timeout=210)
            except asyncio.TimeoutError as exc:
                raise AIError('task_timeout','连通测试超过总时间上限') from exc
            with self.database.connection() as conn:
                # Only deterministic safe metadata; returned model can be arbitrary provider text.
                conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES (?,?,?)',('ai_connection_test',json.dumps({'status':'ok','model':config.model,'item_count':result['item_count'],'latency_ms':result['latency_ms']}),datetime.now(timezone.utc).isoformat()))
            return result
