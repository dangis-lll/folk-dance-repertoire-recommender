# 学生档案、推荐反馈与登录系统开发方案

## 背景

当前系统定位是单人快速扩充民族民间舞剧目数据库：本地录入剧目、挂视频、填写专家评分和文字评价，最后导出 SQLite 数据库。现阶段不需要复杂的多用户权限和专家协作流程，但推荐页已经开始承担真实选剧工作，因此需要减少重复输入学生条件，并让推荐结果反馈能回流到排序逻辑。

本文档记录三个相关功能的技术选型、数据设计和迭代顺序：

- 学生档案
- 推荐结果反馈增强
- 登录/权限系统

## 技术选型

### 后端

继续使用当前技术栈：

- Flask
- SQLite
- Jinja 模板
- 原生 CSS/JavaScript
- `unittest` 测试

理由：

- 项目仍是本地工具和 MVP，不需要引入前后端分离。
- SQLite 适合单机快速扩库、导出和迁移。
- Jinja 页面已经覆盖主要工作流，继续沿用成本最低。

### 数据库

继续使用 SQLite 表迁移方式：

- 在 `SCHEMA` 中添加新表。
- 在 `ensure_schema_migrations()` 中补迁移。
- 对新增表添加必要索引。

暂时不引入 ORM。当前项目 SQL 直接、表结构清晰，ORM 反而会增加重构成本。

### 前端

继续用服务端渲染页面：

- 学生档案列表、新增、编辑使用普通表单。
- 推荐页用 `<select>` 选择学生档案。
- 选择档案后由少量原生 JS 自动填充推荐输入框。

暂时不引入 Vue/React。

## 功能优先级

### P0：学生档案

优先做。

目标：

- 不再每次重复输入同一个孩子的基础条件。
- 推荐记录能关联到具体学生，方便回看。
- 推荐页仍然保留自然语言输入，档案只是帮用户快速生成基础条件。

### P1：推荐反馈增强

保留并加强现有反馈。

目标：

- 记录某个推荐结果为什么合适或不合适。
- 让真实使用反馈逐步影响排序。
- 在剧目详情页能看到历史推荐反馈。

### P2：登录系统

暂时不做完整登录。

理由：

- 当前是单人建库和标注，不需要专家账号、权限分层、审计日志。
- 登录会增加很多非核心开发成本。

可选轻量方案：

- 只在部署到非本机时增加一个环境变量密码，例如 `ADMIN_PASSWORD`。
- 默认本地运行不启用登录。

## 学生档案设计

### 数据表

新增 `student_profile`：

```sql
CREATE TABLE IF NOT EXISTS student_profile (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  gender TEXT DEFAULT '',
  age INTEGER,
  height_cm INTEGER,
  flexibility_level TEXT DEFAULT '',
  strength_level TEXT DEFAULT '',
  control_level TEXT DEFAULT '',
  stamina_level TEXT DEFAULT '',
  coordination_level TEXT DEFAULT '',
  technique_level TEXT DEFAULT '',
  preparation_weeks INTEGER,
  goal TEXT DEFAULT '',
  preferred_ethnicity TEXT DEFAULT '',
  preferred_form TEXT DEFAULT '',
  avoid_common_repertoire INTEGER DEFAULT 0,
  preferences TEXT DEFAULT '',
  constraints TEXT DEFAULT '',
  notes TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

建议索引：

```sql
CREATE INDEX IF NOT EXISTS idx_student_profile_updated_at ON student_profile(updated_at);
CREATE INDEX IF NOT EXISTS idx_student_profile_name ON student_profile(name);
```

字段说明：

- `name`：学生姓名或昵称。
- `gender`：女、男、不限等。
- `age`：年龄。
- `height_cm`：身高。
- `flexibility_level`：weak、medium、high。
- `strength_level`：weak、medium、high。
- `control_level`：weak、medium、high。
- `stamina_level`：weak、medium、high。
- `coordination_level`：weak、medium、high。
- `technique_level`：weak、medium、high。
- `preparation_weeks`：备考或排练周期。
- `goal`：exam、competition、teaching、gala 等。
- `preferred_ethnicity`：例如藏族、蒙古族。
- `preferred_form`：独舞、群舞等。
- `avoid_common_repertoire`：是否避免俗套剧目。
- `preferences`：自由文本偏好。
- `constraints`：自由文本限制。
- `notes`：老师备注。

### 推荐日志关联

给 `recommendation_log` 增加字段：

```sql
ALTER TABLE recommendation_log ADD COLUMN student_profile_id TEXT DEFAULT '';
```

不强制外键，保持 SQLite 导出和手动处理简单。

### 路由

新增页面路由：

- `GET /students`：学生档案列表。
- `GET /students/new`：新增学生档案。
- `POST /students/new`：创建学生档案。
- `GET /students/<student_id>/edit`：编辑学生档案。
- `POST /students/<student_id>/edit`：保存学生档案。
- `POST /students/<student_id>/delete`：删除学生档案。
- `GET /students/<student_id>/recommend`：带档案进入推荐页。

推荐页改造：

- `GET /recommend?student_id=...`
- `POST /recommend` 支持 `student_id`
- `/api/recommend` 支持 `studentProfileId`

### 推荐页交互

推荐页顶部增加：

- 学生档案下拉框。
- “新建档案”按钮。
- “编辑档案”按钮。
- 选择档案后自动生成推荐输入文本。

生成文本示例：

```text
18岁女生，身高165厘米，软度中等，力量中等，控制偏弱，协调性中等，技巧偏弱，有12周准备时间，参加艺考，需要藏族独舞，避免太常见的剧目。
```

用户仍可继续补充：

```text
希望艺术表现空间大，不要太套路。
```

### 后端辅助函数

建议新增：

- `profile_to_query(profile, extra_text='')`
- `student_profile_form_values(form)`
- `create_student_profile(values)`
- `update_student_profile(student_id, values)`
- `student_profile_options()`

### 边界处理

- 如果档案缺少某些字段，不阻塞推荐。
- 推荐页仍然显示缺失条件提示。
- 删除学生档案不删除历史推荐日志，只把档案字段保留为空或历史日志继续保存 `student_profile_id`。

## 推荐反馈增强设计

当前已有 `recommendation_feedback` 表，保留。

建议扩展字段：

```sql
ALTER TABLE recommendation_feedback ADD COLUMN reason_code TEXT DEFAULT '';
ALTER TABLE recommendation_feedback ADD COLUMN note TEXT DEFAULT '';
ALTER TABLE recommendation_feedback ADD COLUMN student_profile_id TEXT DEFAULT '';
```

### 反馈类型

保留现有按钮：

- 合适
- 不合适
- 太难
- 太常见
- 视频资料不足

增加可选原因：

- 身高不合适
- 软度不合适
- 技巧压力大
- 表现空间不足
- 风格不适合
- 准备时间不够
- 视频参考不可靠

### 页面改造

推荐结果卡片保留快捷按钮，同时增加一个小的“补充原因”输入框。

提交字段：

- `log_id`
- `work_id`
- `student_profile_id`
- `rating`
- `reason_code`
- `note`

### 排序回流

当前 `feedback_fit(work_id)` 已经参与推荐分数。可以增强为：

- `fit`：加分。
- `not_fit`：减分。
- `too_hard`：当学生技巧/软度/体能较弱时额外减分。
- `too_common`：当用户要求“不俗套”时额外减分。
- `video_weak`：影响视频维度，不直接否定剧目。

第一阶段不需要复杂模型，只做规则权重即可。

## 登录系统设计

### 当前建议

暂时不做正式用户登录。

理由：

- 标注专家只有一个人。
- 导出只导出 DB 文件。
- 系统主要在本地或可信环境运行。

### 轻量保护方案

如果需要给别人试用，建议只做一个环境变量密码：

```powershell
$env:ADMIN_PASSWORD="your-password"
```

实现方式：

- `GET /login`
- `POST /login`
- `POST /logout`
- Flask session 保存 `authenticated = True`
- `before_request` 保护写操作和导出操作

不做：

- 多用户注册
- 密码找回
- 角色权限
- 专家账号

### 未来多用户版本

如果以后多人使用，再增加：

```sql
CREATE TABLE IF NOT EXISTS app_user (
  id TEXT PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT DEFAULT 'annotator',
  created_at TEXT NOT NULL
);
```

角色：

- `admin`：导入、导出、删除、合并。
- `annotator`：录入剧目、视频、评分。
- `viewer`：只查看和推荐。

但这不是当前阶段的优先事项。

## 导出数据库

当前只需要导出 `.db`，不需要 CSV/JSON。

已采用方案：

- `GET /export/db`
- 使用 Flask `send_file`
- 下载当前 SQLite 数据库文件

注意事项：

- 导出前提交并关闭当前连接，避免 Windows 下文件句柄占用。
- 文件名带时间戳，方便备份。

后续可选：

- 在 README 里说明 DB 文件可以直接备份。
- 增加“导入 DB / 替换 DB”需谨慎，暂不建议做。

## 推荐实施顺序

第一阶段：

1. 新增 `student_profile` 表和迁移。
2. 新增学生档案 CRUD 页面。
3. 推荐页支持选择学生档案并生成查询文本。
4. 推荐日志保存 `student_profile_id`。
5. 补测试。

第二阶段：

1. 推荐反馈增加原因和备注。
2. 推荐日志和反馈关联学生档案。
3. 在剧目详情页显示历史反馈摘要。
4. 优化 `feedback_fit`。

第三阶段：

1. 如果需要对外部署，再加轻量登录。
2. 如果多人协作，再设计正式用户和权限表。

## 测试计划

新增测试建议：

- 创建学生档案成功。
- 编辑学生档案成功。
- 删除学生档案后推荐页不报错。
- 从档案生成推荐输入文本。
- `/recommend?student_id=...` 能显示档案信息。
- `/api/recommend` 支持 `studentProfileId`。
- 推荐日志写入 `student_profile_id`。
- 反馈可以保存 `reason_code` 和 `note`。
- 导出 DB 仍能下载 SQLite 文件。

## 当前不做的事项

- 不做专家 ID 选择。
- 不做专家账号系统。
- 不做多用户权限。
- 不做复杂复核流。
- 不做 CSV/JSON 导出。
- 不引入前端框架。
- 不引入 ORM。

## 总结

当前阶段最值得做的是“学生档案 + 推荐反馈增强”。登录系统可以推迟。这样既能减少重复输入，又能积累真实推荐反馈，还不会拖慢快速扩库的主线。
