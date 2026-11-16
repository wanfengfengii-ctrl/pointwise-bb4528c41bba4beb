# 本地显式维度事实仓

Python 3.11+ 标准库与 SQLite，无安装依赖、联网访问或外部分类标准。用途是解释一个完整本地关系包，校验数值事实，并向指定数据集追加接纳的事实。数据库不存在时创建。

运行完整回归：

    python3.11 -B checks.py

运行小图业务矩阵和真实磁盘演示：

    python3.11 -B scenarios/qualification.py
    python3.11 -B demo.py

完整回归包括全部核心测试、磁盘关闭重开、独立 CLI 子进程、重复回执和 SQLite 完整性检查。文件测试与 demo 的数据库只创建于各自的 TemporaryDirectory，退出清理。

## Python API

    from xbrl_local import Taxonomy, Instance, Warehouse
    taxonomy = Taxonomy.from_file('examples/taxonomy.xml')
    instance = Instance.from_file('examples/accepted.xml')
    with Warehouse('facts.sqlite') as warehouse:
        receipt = warehouse.ingest('lab', 'initial', taxonomy, instance)
        rows = warehouse.read('lab')
        receipts = warehouse.receipts('lab')

Taxonomy.from_xml(text)、Instance.from_xml(text) 支持直接输入 XML 文本；from_file 只读取给定 UTF-8 文件。Warehouse() 使用真实 SQLite 内存数据库。Taxonomy.rules_for(expanded_metric) 返回按来源角色分组的不可变超立方体条件；Taxonomy.qualifies(metric, segment, scenario) 消费展开 QName 到展开 QName 的两个字典，返回布尔值，未知指标抛 InputError。Context、Fact 是解析输出，ingest 的输入必须来自上述解析入口。

QualificationError.issues 按输入事实顺序列出所有不合资格事实的 fact_id、metric、context_id。格式错误抛 InputError，已有业务身份的内容冲突抛其子类 ConflictError；文件和 SQLite 操作错误保留对应异常。成功返回不可变 Receipt(dataset, batch_id, inserted)。read 按事实 id 字符串排序，返回新的字典列表；receipts 按 batch_id 排序。没有读取行意味着空列表。

## 有限 XML 格式

examples/taxonomy.xml 是本项目版本 1 的紧凑关系包格式，根及 concept/arc 元素属于 urn:local-xbrl:1。它将本地已提供的关系写为概念和有向边，不解析 XSD、外部 linkbase、定位器或网络导入。concept 的 name 是 QName，kind 为 metric/cube/dimension/member。arc 必须有 kind、role、from、to，支持 all、notAll、hypercube-dimension、dimension-domain、domain-member、dimension-default。

all/notAll 直接以指标为来源，不做主项目继承。每个来源角色内，全部 all 必须匹配、全部 notAll 必须不匹配；任一角色组成立则指标合格。没有 all/notAll 的指标只接受无显式维度的上下文。不同条件的超立方体不会合并成单个条件。

每条边的 targetRole 缺省为当前 role，指定后决定下一层关系的查找角色。依次从 has-hypercube 边查超立方体的 hypercube-dimension，再查各维度的 dimension-domain 和 domain-member。一个超立方体内，同一维度的多条域路径贡献成员并集，不同维度同时满足。允许有限有向环。dimension-domain/domain-member 的 usable 缺省 true，false 只排除该边目标自身，不阻断后代；同一成员存在另一条可用路径时仍可使用。各边类型的两端种类须正确，重复边拒绝。

all/notAll 的 contextElement 缺省 segment，可为 scenario；closed 缺省 false。匹配超立方体时，其每个维度都必须得到允许成员，closed=true 还要求该容器内没有额外显式维度。另一容器不受该条件的 closed 限制。开放超立方体允许额外的已声明维度及成员。资格判断前，所有显式维度和成员都须有对应概念种类。

dimension-default 是全包唯一的维度到默认成员映射，不允许 targetRole，同维度的第二条默认声明拒绝。必需维度缺省时以默认成员参与当前超立方体匹配；无默认则不匹配。显式写出默认成员一律不合资格，默认不会添入仓内原始维度。

QName 值根据其所在元素的命名空间声明解析，内部统一为 {URI}local。无前缀值使用所在元素默认命名空间；名称限定为 ASCII NCName。实例中的指标元素本身也按命名空间解析。DTD 和实体声明拒绝。

实例采用 xbrli:xbrl、context、entity/identifier、period、unit/measure，以及 xbrldi:explicitMember。支持 segment 与 scenario、ISO 日期的 instant 或 startDate/endDate、单个 QName measure 的单位、普通有限十进制数值。事实需有 id、contextRef、unitRef；decimals 可省略为 INF，也可为带符号整数，仅保留原文，不参与舍入。允许事实先于上下文和单位。XML id 在整份实例中唯一，同一维度在整个上下文只可出现一次。数字原文去除首尾空白后保存，不计算公式，不把 1.0 改写为 1。不支持 typedMember、nil、复合单位、外部引用或完整 XBRL 标准的其他部分。

## 关系包样例与接纳口径

样例中 WideCube 的 Region 域含 North、South、Shared、Forbidden，RegionRoot 和 Hidden 本身不可用，但可穿过 Hidden 到 South。到 North 的两个不同角色继续到 Shared 和 Forbidden，Shared 返回根构成有限环。NarrowCube 只接受 South；BanCube 匹配 Forbidden。WideCube 还需要 Channel，省略时使用 Retail 默认，也可显式用 Wholesale。

Revenue 要求匹配 WideCube 且不匹配 BanCube；Expense 要求 NarrowCube；Combined 同角色要求两个正超立方体同时匹配；Alternative 的两个来源角色分别提供可选条件。OpenMetric 允许额外维度，ScenarioMetric 在 scenario 中匹配 North，Bare 无维度关系。

examples/accepted.xml 的完整接纳身份为 a 至 i；examples/rejected.xml 中 ok 合格，而 bad-b、bad-ban、bad-hidden、bad-default、bad-extra、bad-missing 不合格，因此该批整体拒绝。scenarios/qualification.py 另逐项列出 7 个指标与 13 个上下文的独立期望，共 91 个组合、19 个接纳身份，并核对共享上下文的两个输入次序。

## 存储和重复导入

一个数据集由第一次成功导入绑定分类标准 XML 的 UTF-8 文本 SHA-256；包内空白变化也构成不同包身份。SQLite user_version=1，未知版本拒绝打开。事实身份为 (dataset, id)，值包含指标、原 context id、实体、期间、两个原始显式维度字典、展开单位、数值和 decimals 原文。

同身份相同内容不重复增加行；不同内容整批 ConflictError，不提供订正或删除接口。批次身份为 (dataset, batch_id)。规范化后事实按 id 排序计算批次指纹，事实换序可重放，未使用上下文不参与指纹。同批同内容返回最初回执；同批不同内容拒绝。另一个批次引用已存在相同事实可产生 inserted=0 的新回执。数据集之间身份独立。

入仓按指标与上下文共同求资格，整批资格通过后，在 BEGIN IMMEDIATE 事务中检查身份、追加所有事实和回执。一批含任意无效事实或身份冲突时，既有事实、数据集绑定和回执保持不变；修正失败批次后可使用原批次号重试。历史回执的 inserted 不受后续导入影响。

## CLI

    python3.11 -B -m xbrl_local --db facts.sqlite import --dataset lab --batch initial --taxonomy examples/taxonomy.xml --instance examples/accepted.xml
    python3.11 -B -m xbrl_local --db facts.sqlite read --dataset lab

成功向 stdout 输出 JSON 并退出 0。格式、资格、身份、文件或 SQLite 操作错误输出含 error 的 JSON 并退出 2；资格错误另含 issues。参数用法错误由 argparse 报告。命令只使用显式指定的文件，示例 facts.sqlite 创建在当前项目目录。
