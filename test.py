from notion_client import Client
from dotenv import load_dotenv
import os
"""
load_dotenv()
notion = Client(auth=os.getenv("NOTION_TOKEN"))
DATABASE_ID = "2c9644ead11a806489b3c4e3f0109e7c"
DATA_SOURCE_ID = "2c9644ea-d11a-8061-9707-000be0590cf4"

resp = notion.databases.retrieve(database_id=DATABASE_ID)
print(resp)
test2=notion.data_sources.query(data_source_id=DATA_SOURCE_ID)
print(test2)
"""
load_dotenv()
notion = Client(auth=os.getenv("NOTION_TOKEN"))
DATABASE_ID = "2d0644ead11a80148722fe665c10440e"
DATA_SOURCE_ID = "2d0644ea-d11a-80b6-a7a8-000b147d83a0"
#如果你想要修改数据,只能通过数据源条目来修改
resp = notion.databases.retrieve(database_id=DATABASE_ID)
print(resp)
test2=notion.data_sources.query(data_source_id=DATA_SOURCE_ID)
print(test2)