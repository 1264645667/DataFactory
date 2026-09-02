"""造数策略包（策略模式）

- base: 策略抽象基类与字段类型解析工具
- registry: 12 种策略注册表
- string_strategies: DEFAULT/RANDOM_FIXED_LEN/RANDOM_RANGE_LEN/CUSTOM_VALUE/PICK_FROM_LIST/ITERATE_LIST
- number_strategies: INCR_FROM（Redis 批量预取）
- time_strategies: NOW/RANDOM_TIME_RANGE/FIXED_TIME
- pk_strategies: UUID/SNOWFLAKE（雪花算法自实现）
"""
