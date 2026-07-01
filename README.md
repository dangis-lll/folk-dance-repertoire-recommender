# 中国民族民间舞剧目智能查询系统

Flask + SQLite + DeepSeek API 实现。系统不存视频本体，只存剧目信息、视频链接、专家评分、推荐记录。

## 功能

- 剧目库：新增、编辑、查询剧目，支持别名、民族、地区、舞蹈类型等属性
- 视频版本：同一个剧目可挂多个平台链接（B站、YouTube 等）
- 专家评分：按身体要求、学习成本、表演要求、使用场景打分
- 帮我选剧目：自然语言输入学生条件，结合专家评分和全文索引智能推荐
- 批量导入：支持 CSV 批量导入剧目和视频链接
- 数据采编工作台：B站关键词自动搜索，人工确认后入库
- 视频浏览：YouTube/B站优先内嵌预览，其他平台保留跳转
- 数据治理：重复检测、剧目合并、资料完整性检查

## 开发文档

- [学生档案、推荐反馈与登录系统开发方案](docs/feature-roadmap.md)

## 安装与启动

依赖 Python 3，推荐使用 conda 环境。

```powershell
# 设置 DeepSeek API Key（可选，未配置时使用本地规则解析）
$env:DEEPSEEK_API_KEY="你的 deepseek key"

# 启动
conda run -n env python app.py
```

打开出现的网址即可使用。首次启动会自动创建数据库并写入示例数据。

隐藏自动搜索：

```powershell
$env:APP_MODE="institution"
conda run -n env python app.py
```
