# -*- coding: utf-8 -*-
"""飞书客户端：获取 token、解析 wiki 节点为多维表 app_token、读取记录。"""
import time
import requests

BASE = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self._tok = None
        self._tok_exp = 0

    # ---- 凭证（带缓存，过期前自动刷新）----
    def token(self) -> str:
        if self._tok and time.time() < self._tok_exp - 60:
            return self._tok
        r = requests.post(
            f"{BASE}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=15,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        self._tok = data["tenant_access_token"]
        self._tok_exp = time.time() + int(data.get("expire", 7200))
        return self._tok

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ---- 把 wiki 节点解析成多维表 app_token ----
    def resolve_app_token(self, node_token: str) -> str:
        r = requests.get(
            f"{BASE}/wiki/v2/spaces/get_node",
            params={"token": node_token},
            headers=self._headers(),
            timeout=15,
        )
        data = r.json()
        if data.get("code") != 0:
            raise RuntimeError(f"解析 wiki 节点失败: {data}")
        node = data["data"]["node"]
        if node.get("obj_type") != "bitable":
            raise RuntimeError(f"该 wiki 节点不是多维表，obj_type={node.get('obj_type')}")
        return node["obj_token"]

    # ---- 读取一张表的全部记录（自动翻页）----
    def fetch_records(self, app_token: str, table_id: str, page_size: int = 500):
        items, page_token = [], None
        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            r = requests.post(
                f"{BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                params=params,
                headers=self._headers(),
                json={},  # 空 body = 取全部；如需服务端过滤可在此加 filter
                timeout=30,
            )
            data = r.json()
            if data.get("code") != 0:
                raise RuntimeError(f"读取记录失败 (table={table_id}): {data}")
            d = data.get("data", {})
            items.extend(d.get("items", []) or [])
            if d.get("has_more") and d.get("page_token"):
                page_token = d["page_token"]
            else:
                break
        # 只返回每条记录的 fields 字典
        return [it.get("fields", {}) for it in items]
