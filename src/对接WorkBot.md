对接WorkBot
##BaseURL：https://flowbot.feiliu.run
##配置机器人回调地址API
url = "https://flowbot.feiliu.run/api/updateCallBackUrl?robotId=b1395e58b79ca910aa34330efdba47cb"

payload = json.dumps({
   "callBackUrl": "http://x.com/robot/callback/123"
})
headers = {
   'Content-Type': 'application/json'
}
##robotID为机器人ID
##发送文本消息:https://flowbot.feiliu.run/api/sendTask
  url = "https://flowbot.feiliu.run/api/sendTask?robotId=b1395e58b79ca910aa34330efdba47cb"

payload = json.dumps({
   "taskList": [
      {
         "type": 10001,
         "searchText": "用户昵称/备注（存在备注时只能用备注）",
         "message": "消息内容"
      }
   ]
})
headers = {
   'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)
##发送@群成员消息 https://flowbot.feiliu.run/api/sendTask
 url = "https://flowbot.feiliu.run/api/sendTask?robotId=b1395e58b79ca910aa34330efdba47cb"

payload = json.dumps({
   "taskList": [
      {
         "type": 50009,
         "atList": [
            "少年·Sure",
            "@所有人"
         ],
         "searchText": "测试群-001",
         "message": "WorkBot,一款安全稳定零封号的微信/企微RPA机器人"
      }
   ]
})
headers = {
   'Content-Type': 'application/json'
}

response = requests.request("POST", url, headers=headers, data=payload)


##桥接RPA机器人(FlowBot)和后端知识库服务(Dify),实现企微外部群的机器人功能,
1.创建workbot的回调接口
2.调用 配置机器人回调地址API进行回调接口配置
3.参照回调接口说明实现回调接口消息处理,相关消息类型请查看 https://flowbot.apifox.cn/doc-5369842
4.相关消息调用dify_client的chat_blocking进行处理
5.根据接受消息的类型进行消息回复
  5.1 调用发送文本消息API进行发送
  5.2.如果是群消息，则调用发送@群成员消息API进行发送



根据回调接口说明进行优化https://flowbot.apifox.cn/doc-5369842
1.如果是群聊消息"groupNickname":"用户昵称/备注",//限群聊 "corpsName":"@微信/主体名称"//限群聊 ;
只处理群聊消息是@{我的昵称}的消息;
2.我的昵称通过 https://flowbot.apifox.cn/api-227582604 的接口获得，在创建机器人时配置

next step：nickname和name都需要，匹配到一个就算

next setp: 针对wortbot要定期监测回调接口是否正常，如果不正常，则应该重新启动服务


1.持久化存储workbot收到的消息，并记录时间，用于定期监测
2.持久化数据库使用mysql;设计数据库结构message(messageid,messagetime,robotid,mode,groupname,messagetype,groupnickname,corpsName,message);可根据三范式原则设计其他表结构；
持久化存储的消息对象见 https://flowbot.apifox.cn/doc-5369842
3.数据库配置为 127.0.0.1:3306
MYSQL_PASSWORD=infini_rag_flow
# The hostname where the MySQL service is exposed
MYSQL_HOST=127.0.0.1 3306
# The database of the MySQL service to use
MYSQL_DBNAME=workbot


对于收到的消息，需要跟数据库的信息进行比对(使用groupname,groupnickname,raw_json关联)，如果消息存在,则为已处理消息，无需调用_handle_log_item进行处理，并在日志中提示该消息已处理

##架构变成并行处理:
这个处理消息需要改成队列+并行调度，将所有需要处理的消息放入队列,然后启动指定数量的线程进行消息处理，请帮我重构代码;消息需要持久化处理,启动时需要读取未处理的消息，并继续处理;


@聚源数据字典小助手N 公募基金获奖情况都有哪些来源  

基金停复牌的数据有吗？有的话，在哪个表里啊 @聚源数据字典小助手N


@聚源数据字典小助手N  评价下天天基金，私募排排网

@聚源数据字典小助手N 评价下恒生



支持多个机器人
1.创建多个机器人，并配置多个回调接口,回调接口增加botid参数
2.根据botid参数进行消息处理并回复给对应的机器人
请根据上述需求重构代码，并给出重构后的代码

## 消息查询 API

在 `config/.env` 中设置以下配置后，查询接口会挂载到现有 WorkBot webhook 服务，
默认复用 Docker 映射的 `8090` 端口。Token 为空时接口不会注册。

```env
WORKBOT_QUERY_API_TOKEN=请替换为足够长的随机密钥
# WORKBOT_QUERY_API_PATH=/api/workbot
# WORKBOT_QUERY_MAX_RANGE_DAYS=31
```

请求必须携带请求头：

```text
Authorization: Bearer 请替换为足够长的随机密钥
```

两个接口都必须提供 `robotid`、`start_time`、`end_time`。时间使用 ISO 8601；
带时区的时间会转换成 UTC，结束时间不包含在查询范围内。单次最多返回 200 条，
默认最多查询 31 天。

查询 `message`：

```bash
curl -G 'http://127.0.0.1:8090/api/workbot/messages' \
  -H 'Authorization: Bearer 你的密钥' \
  --data-urlencode 'robotid=robot_id_1' \
  --data-urlencode 'start_time=2026-07-01T00:00:00+08:00' \
  --data-urlencode 'end_time=2026-07-02T00:00:00+08:00' \
  --data-urlencode 'process_status=done' \
  --data-urlencode 'limit=100'
```

可选条件：`messageid`、`mode`、`groupname`、`groupnickname`、`messagetype`、
`process_status`、`before_id`、`limit`。

查询 `callback_log`：

```bash
curl -G 'http://127.0.0.1:8090/api/workbot/callback-logs' \
  -H 'Authorization: Bearer 你的密钥' \
  --data-urlencode 'robotid=robot_id_1' \
  --data-urlencode 'start_time=2026-07-01T00:00:00Z' \
  --data-urlencode 'end_time=2026-07-02T00:00:00Z' \
  --data-urlencode 'mode=logs'
```

可选条件：`mode`、`before_id`、`limit`。当返回的 `next_before_id` 不为空时，
把它作为下一次请求的 `before_id`，即可继续翻页。

## Vue 3 可视化查询界面

项目已在 `frontend/` 中提供 Vue 3 + Vite 前端。启动整个 Compose：

```bash
docker compose up -d --build
```

浏览器访问 `http://服务器地址:8091`，输入 `WORKBOT_QUERY_API_TOKEN`、机器人 ID
和时间范围即可查询。界面支持两个数据表切换、消息条件筛选、游标翻页、JSON
详情查看、当前页导出，以及服务日志的在线浏览和下载。Token 仅保存在浏览器
当前会话中，并通过 Authorization 请求头发送。

日志接口只允许访问 `LOG_FILE` 指定的当前文件及其合法轮转文件，不接受任意
文件路径。在线预览默认读取末尾 500 行，最多可请求 5000 行且响应内容不超过
2 MiB；下载接口返回未经裁剪的原始文件。
