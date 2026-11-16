# 按申报精度联合核验计算关系

本扩展直接使用 README.md 的 Taxonomy.from_xml/from_file、Instance.from_xml/from_file 和 Warehouse.ingest(dataset,batch_id,taxonomy,instance)。保留原接口、原文存储、维度资格、批次重放、身份冲突和全部原回归。现有实现尚不接受计算边；这里的 XML 与构造器是新功能输入样例，不是已实现的核验器。使用 Python 标准库与 SQLite，不引入第三方求解器。

## 计算关系

关系包的 arc 新增 kind="summation-item"，属性恰为 kind、role、from、to、weight，全部必填，不接受其他属性；QName 沿用所在元素作用域规则。两端均须为已声明的 metric。weight 使用实例数值相同的普通有限十进制文法，且非零，不接受指数、NaN 或 INF。同一展开后的 (role,from,to) 不得重复，即使权重不同也拒绝。每包参与计算边的不同指标至多8个，不同 (role,from) 至多8组；违反上述约定抛 InputError。允许负权重、自环及循环，不增加计算图无环要求。

每组 (role,from) 表达 from 等于该组各 to 乘对应 weight 之和。一个计算指标指至少作为一条计算边端点出现的指标。原维度边的语义不变，计算边不参与维度资格判断；不含计算边的包行为不变。新增关系的内部访问接口由实现者决定。

## 经济方面和精度

经济方面由实体scheme及identifier、期间、segment与scenario原始显式维度映射、展开单位共同组成，不含context ID、事实ID及指标；不补默认维度。同一方面同一计算指标的全部事实共享一个有理数真值。

数值v和整数decimals=d表示闭区间[v−10^(−d)/2,v+10^(−d)/2]，INF表示单点；不同事实的区间取交集，空交集即不一致，原文仍原样保存。decimals省略仍沿用INF。负decimals、负数值和零值均合法。非计算指标继续按原口径入仓，不作重复精度交集核验。计算指标即使尚未参与完整等式，也须满足自身全部事实区间的交集非空。

每次新批次入仓，对该数据集既有事实与本批候选事实的最终集合核验：某组计算边的父指标及全部子指标均在该方面出现时，整组等式生效，否则整组暂不生效；所有角色中生效的等式共享上述真值，须与全部区间同时存在有理数解。允许全量重算，无增量复杂度要求。不能用逐条等式分别可满足或浮点容差代替联合可满足。只有当前数据集参与核验，不跨数据集拼接。相同事实身份、相同内容的重投只保留一份；不同事实ID即使申报相同经济方面，也不合并原始存储行。

## 接纳和错误

沿用格式、资格、批次与事实身份检查；这些检查通过后，计算不一致抛新增CalculationError，继承InputError。从 xbrl_local 导出此异常；字符串以 CALCULATION_INCONSISTENT 开头。原 CLI 的 InputError 处理方式继续适用，不要求扩展 CLI 的 JSON 字段。

异常的groups列出全部不一致方面，每项含aspect及该方面全部计算指标事实的升序fact_ids；groups按aspect的排序键JSON文本排序，JSON采用ensure_ascii=False、sort_keys=True及紧凑分隔符。不要求最小冲突子集。groups 为字典列表，每项恰有 aspect、fact_ids 两键；包括既有与候选的计算事实身份，不含非计算指标事实。aspect 恰有 entity、period、segment、scenario、unit 五键：entity 为含 scheme、identifier 的字典；period 沿用 read 行中的 instant:日期 或 duration:起日/止日 字符串；segment、scenario 为展开QName映射；unit 为展开QName字符串。JSON排序键只用于排序，不用JSON文本替代aspect对象。

失败时事实、数据集绑定和回执全部不变；成功仍返回原Receipt，关闭重开后继续联合核验。同批同内容重放保持原回执，不产生新行；同批或同事实异内容仍为ConflictError。首次批次计算失败不能留下数据集绑定，之后可用同批次号及另一关系包重试。既有SQLite事务可复用，不要求新建恢复机制。

## 可运行输入与预期

examples/calculation-taxonomy.xml 定义 P=X 和 Q=X。examples/calculation-first.xml 含 x:X=0.5、decimals=0 及 p:P=0、decimals=INF，同方面无维度。使用相同关系包，先把 first 导入 lab/first，返回 Receipt('lab','first',2)。随后导入 examples/calculation-second.xml 到 lab/second，其中 q:Q=1、decimals=INF，须抛 CalculationError。其 groups 恰为：
```json
[{"aspect":{"entity":{"scheme":"urn:calculation:entity","identifier":"E"},"period":"instant:2026-10-31","segment":{},"scenario":{},"unit":"{urn:calculation:unit}count"},"fact_ids":["p","q","x"]}]
```
此时 lab 的原始事实仍仅 p、x，回执仅 first；X 的闭区间为[0,1]，P与Q各自可与X相等，但不存在共同真值。第二份的context ID和unit ID刻意不同，不构成不同方面。

examples/calculation-other-period.xml 的 q 属于2026-11-01，替代 second 导入同一 lab/second 则返回 inserted=1；Q所在方面的关系缺X，暂不激活。把 first 与 second 的事实放进同一批也须失败。calculation_samples.py 只构造普通XML，直接运行核对样例的解析值，不执行目标计算功能。

完成后可沿 README.md 的原 Python 入口或 CLI 导入这些文件；正常两步演示需在代码中捕获预期 CalculationError，展示错误分组及失败后的事实和回执，再关闭重开核对。

## 交付和核验

交付计算关系解析、经济方面绑定、精确联合核验与入仓接入，并简述共享变量、重复事实和核验到提交的正确性不变量。保留原测试字节，新增独立核验覆盖端点相交、负decimals、INF、重复事实空交集、负权重、自环、循环、秩亏、缺子项补齐、不同方面隔离和失败重开。用小规模独立精确参照核对联合判定，包含仅低维可行的退化情形，不用浮点采样充当参照。记录8指标边界的核验耗时，不设未公开的运行时门槛。

沿用现有 .pointwise-runtime.json 的格式：version=1、kind=cli，setup 为准备命令的argv数组列表，verify、demo 各为一个argv数组。更新verify使其运行全部原回归及新增业务核验，demo保留原演示并展示上述真实跨批接纳、联合拒绝和重开结果；可新增聚合入口。无需新增安装、服务或调度功能。

不实现外部分类标准、完整XBRL calculation linkbase、单位换算、默认维度补全、期间推导、事实订正撤销、增量求解、最小冲突集或数据集换包。
