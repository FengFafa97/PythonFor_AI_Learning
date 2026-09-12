from dataclasses import dataclass
from typing import Literal, Optional
import json

@dataclass
class AgentRunResult:
    """run() 的结构化返回：调用方靠字段判断，不用再猜字符串内容。"""
    success: bool
    content: Optional[str] = None                     # 成功时有值
    error_type: Optional[Literal["max_steps"]] = None  # 失败时有值
    error_message: Optional[str] = None                # 失败时的人类可读描述


class Agent:

    def __init__(self, llm, tools, permission_checker, user):
        self.llm = llm
        self.tools = tools
        self.permission_checker = permission_checker
        self.user = user

    def run(self, user_message):

        history = [
            {
                "role" : "user",
                "content" : user_message
            }
        ]

        max_step = 10


        for step in range(max_step):
            response = self.llm.chat(
                message = history,
                tools = self.tools.schemas()
            )

            if not response.tool_calls:
                return AgentRunResult(success=True, content=response.content)

            history.append({
                "role": "assistant",
                "content": response.content if response.content is not None else "",
                "tool_calls": response.tool_calls
            })


            for tool_call in response.tool_calls:

                tool_name = tool_call.function.name

                try:
                    argument = json.loads(tool_call.function.arguments)
                except Exception as e:
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Argument Json 解析失败"
                    }
                    history.append(tool_result)
                    continue
                allowed = self.permission_checker.check(
                    user = self.user,
                    tool_name = tool_name,
                    argument = argument
                )
                if not allowed["allowed"]:
                    tool_result = {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": "Permission denied"
                    }
                    history.append(tool_result)                  
                else:

                    tool = self.tools.get(tool_name)
                    if not tool:
                        tool_result = {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": f"没有名为 {tool_name} 的工具"
                        }
                        history.append(tool_result)                      
                    else:
                        try:
                            tool_result = {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": tool.execute(**argument)
                            }
                            history.append(tool_result)                          
                        except Exception as e:
                            tool_result = {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content":str(e)
                            }
                            history.append(tool_result)
        return AgentRunResult(
            success=False,
            error_type="max_steps",
            error_message="任务执行步骤超过限制，无法继续。"
        )
      
class Tools:
    def __init__(self,*tools):

        self._tools = {}
        for tool in tools:
            self._tools[tool.name] = tool

    def schemas(self):

        result = []

        # 遍历所有工具对象
        for tool in self._tools.values():

            # 获取这个工具的 Schema
            schema = tool.schema()

            # 放进列表
            result.append(schema)

        return result
    
    def get(self,name):

        return self._tools.get(name)

class QueryMoiveTicketPrice:

    name = "query_ticket_price"

    def execute(self,movie_name:str):

        price ={
            "lalaland":{
                        "price" : 45,
                        "On sale" : True,
                        "stock":500
            },
            "moonboy":{
                        "price" : 50,
                        "On sale" : False,
                        "stock":423
            }
        }
        moiveprice = price.get(movie_name)

        if moiveprice is None:
            return{
                "success":False,
                "message" : f"{movie_name}的电影票已售罄"
            }
        return{
            "success":True,
            "movie_name":movie_name,
            "stock":moiveprice["stock"],
            "price":moiveprice["price"]
        }
    def schema(self):
    #告诉 LLM 这个工具是什么、需要什么参数

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "查询指定电影票价。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "movie_name": {
                            "type": "string",
                            "description": "电影名字"
                        }
                    },
                    "required": ["movie_name"],
                    "additionalProperties": False
                }
            }
    }

class BuyMoiveTicket:

    name = "buy_ticket"

    def execute(self,movie_name:str):

        moive ={
            "lalaland":{
                        "price" : 45,
                        "On sale" : "Yes",
                        "stock":500
            },
            "moonboy":{
                        "price" : 50,
                        "On sale" : "No",
                        "stock":423
            }
        }
        movietinfo = moive.get(movie_name)

        if movietinfo is None:
            return {
                "success": False,
                "message": f"没有找到电影：{movie_name}"
            }
        
        if movietinfo["stock"] == 0:
            return{
                "success":False,
                "message" : f"{movie_name}的电影票已售罄"
            }
        return{ "success":True,
                "movie_name":movie_name,
                "stock":movietinfo["stock"] - 1,
                "price":movietinfo["price"],
                "message" : f"您的{movie_name}电影票已购买成功"
            }
    def schema(self):
    #告诉 LLM 这个工具是什么、需要什么参数

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "购买指定电影。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "movie_name": {
                            "type": "string",
                            "description": "电影名字"
                        }
                    },
                    "required": ["movie_name"],
                    "additionalProperties": False
                }
            }
    }

class PermissionManager:
    def __init__(self):

        self.permission = {
            "guest":{
                "query_ticket_price"
            },
            "buyer":{
                "query_ticket_price",
                "buy_ticket"
            },
            "manager":{
                "query_ticket_price",
                "buy_ticket",
                "change_discount"
            },
        }
    def check(self,user,tool_name,argument):

        try:
            role = user["role"]

            permission = self.permission.get(role,set())

            if tool_name in permission:
                return{
                    "allowed":True,
                    "message":"允许执行"
                }
            return{
                "allowed":False,
                "message":f"角色 {role} 没有执行 {tool_name} 的权限"
            }                   
        except Exception as e:
            argument = str(e)
            return{
                "allowed":False,
                "message":argument
            }  
            

