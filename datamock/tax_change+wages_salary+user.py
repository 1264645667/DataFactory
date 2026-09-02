import time
import random
import datetime
import uuid
import logging
from typing import Dict, List, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from common.mysqldb import OptimizedMySQLCommon

import numpy as np


class NumpyTaxCalculator:
    """numpy-->税款计算器"""

    @staticmethod
    def calculate_tax_batch(incomes: np.ndarray) -> Dict[str, np.ndarray]:
        """
        批量计算税款数据（使用numpy向量化计算）

        税率表：
        累计应纳税所得额 <= 36000: 税率=3%，速算扣除数=0
        36000 < x <= 144000: 税率=10%，速算扣除数=2520
        144000 < x <= 300000: 税率=20%，速算扣除数=16920
        300000 < x <= 420000: 税率=25%，速算扣除数=31920
        420000 < x <= 660000: 税率=30%，速算扣除数=52920
        660000 < x <= 960000: 税率=35%，速算扣除数=85920
        x > 960000: 税率=45%，速算扣除数=181920
        """
        # 计算应纳税所得额
        deduction_cost = 5000.0  # 本期减除费用
        cost_rate = 0.2  # 费用为收入的20%

        # 向量化计算
        costs = incomes * cost_rate
        taxable_incomes = np.maximum(0, incomes - deduction_cost - costs)

        # 初始化税率和速算扣除数数组
        rates = np.zeros_like(taxable_incomes)
        quick_deductions = np.zeros_like(taxable_incomes)

        # 使用向量化条件判断
        conditions = [
            taxable_incomes <= 36000,
            (taxable_incomes > 36000) & (taxable_incomes <= 144000),
            (taxable_incomes > 144000) & (taxable_incomes <= 300000),
            (taxable_incomes > 300000) & (taxable_incomes <= 420000),
            (taxable_incomes > 420000) & (taxable_incomes <= 660000),
            (taxable_incomes > 660000) & (taxable_incomes <= 960000),
            taxable_incomes > 960000
        ]

        rate_values = [0.03, 0.10, 0.20, 0.25, 0.30, 0.35, 0.45]
        deduction_values = [0, 2520, 16920, 31920, 52920, 85920, 181920]

        # 应用条件
        for cond, rate, deduction in zip(conditions, rate_values, deduction_values):
            rates = np.where(cond, rate, rates)
            quick_deductions = np.where(cond, deduction, quick_deductions)

        # 计算应纳税额
        tax_amounts = taxable_incomes * rates - quick_deductions
        tax_amounts = np.maximum(0, tax_amounts)  # 确保非负

        return {
            'incomes': incomes,
            'deduction_costs': np.full_like(incomes, deduction_cost),
            'costs': costs,
            'taxable_incomes': taxable_incomes,
            'rates': rates,
            'quick_deductions': quick_deductions,
            'tax_amounts': tax_amounts,
            'accumulated_incomes': incomes,
            'accumulated_costs': costs,
            'accumulated_taxable_incomes': taxable_incomes,
            'accumulated_taxable_amounts': tax_amounts
        }

    @staticmethod
    def generate_id_cards_batch(num_cards: int, tax_no_index: int, start_index: int) -> np.ndarray:
        """批量生成身份证号"""
        area_codes = np.array(['110101', '310104', '440301', '510104', '330102'])

        # 选择区域代码
        area_code = area_codes[tax_no_index % len(area_codes)]

        # 生成出生日期（1970-2000年）
        years = 1970 + np.random.randint(0, 31, num_cards)
        months = np.random.randint(1, 13, num_cards)
        days = np.random.randint(1, 29, num_cards)  # 简单假设每月最多28天

        # 顺序码
        sequence_codes = np.random.randint(0, 1000, num_cards)

        # 前17位
        first_17s = np.array([
            f"{area_code}{year:04d}{month:02d}{day:02d}{seq:03d}"
            for year, month, day, seq in zip(years, months, days, sequence_codes)
        ])

        # 计算校验码
        weights = np.array([7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2])
        check_codes = np.array(['1', '0', 'X', '9', '8', '7', '6', '5', '4', '3', '2'])

        id_cards = []
        for first_17 in first_17s:
            total = np.sum([int(digit) * weight for digit, weight in zip(first_17, weights)])
            check_code = check_codes[total % 11]
            id_cards.append(first_17 + check_code)

        return np.array(id_cards)


# ============================================================================
# 动态数据生成器
# ============================================================================

class DynamicDataGenerator:
    """动态数据生成器，支持动态表名获取"""

    def __init__(self, mysql_common: OptimizedMySQLCommon):
        self.mysql_common = mysql_common

    def get_tax_configs(self) -> List[Dict[str, str]]:
        """
        从数据库获取税号配置

        Returns:
            List of dicts with keys: belong_tax_no, customer_tax_no, customer_name, record_id
        """
        query = """
        SELECT belong_tax_no, customer_tax_no, customer_name, record_id 
        FROM agent_declaration_info
        WHERE customer_tax_no IN (
            'SQL1111111111123', 'SQL1111111111124', 'SQL1111111111125',
            'SQL1111111111126', 'SQL1111111111127', 'SQL1111111111128',
            'SQL1111111111129', 'SQL1111111111130', 'SQL1111111111131',
            'SQL1111111111132', 'SQL1111111111133', 'SQL1111111111134',
            'SQL1111111111135', 'SQL1111111111136', 'SQL1111111111137',
            'SQL1111111111138', 'SQL1111111111139'
        ) AND declaration_period = '2025-12'
        """

        try:
            results = self.mysql_common.execute_query(query)

            tax_configs = []
            for row in results:
                config = {
                    'belong_tax_no': row['belong_tax_no'],
                    'customer_tax_no': row['customer_tax_no'],
                    'customer_name': row['customer_name'],
                    'declaration_id': row['record_id']
                }
                tax_configs.append(config)

            print(f"✅ 从数据库获取到 {len(tax_configs)} 个税号配置")
            return tax_configs

        except Exception as e:
            print(f"❌ 获取税号配置失败: {e}")
            # 返回硬编码配置作为后备
            return self._get_fallback_configs()

    def _get_fallback_configs(self) -> List[Dict[str, str]]:
        """获取后备配置（硬编码）"""
        configs = [
            ("9151010K9A6C712310", "91338899POPSICLE0", "雪糕联调01科技有限公司",
             "063bf456-d245-4fea-8737-b1c4b8673027"),
        ]

        return [
            {
                'belong_tax_no': config[0],
                'customer_tax_no': config[1],
                'customer_name': config[2],
                'declaration_id': config[3]
            }
            for config in configs
        ]

    def get_table_suffix_mapping(self, tax_nos: List[str]) -> Dict[str, str]:
        """
        获取分表后缀映射

        Args:
            tax_nos: 税号列表

        Returns:
            字典，键为税号，值为分表后缀
        """
        if not tax_nos:
            return {}

        # 构建IN查询
        placeholders = ', '.join(['%s'] * len(tax_nos))
        query = f"""
        SELECT tax_no, table_id 
        FROM tax_database_route_by_customer_tax_no 
        WHERE tax_no IN ({placeholders})
        """

        try:
            results = self.mysql_common.execute_query(query, tuple(tax_nos))

            mapping = {}
            for row in results:
                mapping[row['tax_no']] = str(row['table_id'])

            print(f"✅ 获取到 {len(mapping)} 个税号的分表映射")

            # 检查是否有税号没有分表映射
            missing_tax_nos = [tax_no for tax_no in tax_nos if tax_no not in mapping]
            if missing_tax_nos:
                print(f"⚠️  以下税号没有分表映射，将使用默认后缀 '101': {missing_tax_nos}")
                for tax_no in missing_tax_nos:
                    mapping[tax_no] = "101"

            return mapping

        except Exception as e:
            print(f"❌ 获取分表信息失败: {e}")
            # 返回默认映射
            return {tax_no: "101" for tax_no in tax_nos}

    def get_max_ids_for_suffix(self, table_suffix: str) -> Dict[str, int]:
        """获取指定分表后缀的三张表的最大ID"""
        print(f"🔍 查询分表后缀 {table_suffix} 的最大ID...")

        table_names = {
            'tax_change': f"tax_change_{table_suffix}",
            'agent_declaration_user': f"agent_declaration_user_{table_suffix}",
            'agent_declaration_salary_wages_info': f"agent_declaration_salary_wages_info_{table_suffix}"
        }

        max_ids = {}

        try:
            for key, table_name in table_names.items():
                query = f"SELECT COALESCE(MAX(id), 0) as max_id FROM {table_name}"
                result = self.mysql_common.execute_query(query)
                max_ids[key] = result[0]['max_id'] if result else 0
                print(f"✅ {table_name} 最大ID: {max_ids[key]:,}")

        except Exception as e:
            print(f"❌ 查询分表 {table_suffix} 的最大ID失败: {e}")
            max_ids = {
                'tax_change': 0,
                'agent_declaration_user': 0,
                'agent_declaration_salary_wages_info': 0
            }

        return max_ids

    def generate_person_batch_numpy(self, tax_config: Dict, start_index: int,
                                    batch_size: int, tax_no_index: int) -> List[Dict[str, Any]]:
        """numpy-->批量生成人员信息"""

        # 生成随机收入
        incomes = np.random.uniform(3000, 20000, batch_size).round(2)

        # 批量计算税款数据
        tax_data = NumpyTaxCalculator.calculate_tax_batch(incomes)

        # 批量生成身份证号
        id_cards = NumpyTaxCalculator.generate_id_cards_batch(batch_size, tax_no_index, start_index)

        # 生成人员信息
        persons = []
        current_time = datetime.datetime.now()

        for i in range(batch_size):
            person_id = start_index + i
            id_card = id_cards[i]

            # 从身份证号提取出生日期
            birth_year = int(id_card[6:10])
            birth_month = int(id_card[10:12])
            birth_day = int(id_card[12:14])
            birth_date = datetime.date(birth_year, birth_month, birth_day)

            person = {
                'id': person_id,
                'belong_tax_no': tax_config['belong_tax_no'],
                'customer_tax_no': tax_config['customer_tax_no'],
                'customer_name': tax_config['customer_name'],
                'declaration_id': tax_config['declaration_id'],
                'declaration_period': '2025-12',
                'id_card_no': id_card,
                'name': f'测试人员{person_id}',
                'user_id': str(uuid.uuid4()),
                'birthday': birth_date.strftime("%Y-%m-%d"),
                'sex': random.randint(1, 2),
                'nationality': '156',
                'education': random.choice(['研究生', '大学本科', '大学本科以下']),
                'mobile': f'1{random.randint(300000000, 999999999):09d}',
                'income': float(incomes[i]),
                'deduction_cost': float(tax_data['deduction_costs'][i]),
                'cost': float(tax_data['costs'][i]),
                'taxable_income': float(tax_data['taxable_incomes'][i]),
                'tax_rate': float(tax_data['rates'][i]),
                'quick_deduction': float(tax_data['quick_deductions'][i]),
                'tax_amount': float(tax_data['tax_amounts'][i]),
                'current_time': current_time
            }
            persons.append(person)

        return persons


# ============================================================================
# 批量插入器
# ============================================================================

class OptimizedBatchInserter:
    """批量插入器"""

    def __init__(self, mysql_common: OptimizedMySQLCommon, table_name: str,
                 insert_query: str, batch_size: int = 10000):
        self.mysql_common = mysql_common
        self.table_name = table_name
        self.insert_query = insert_query
        self.batch_size = batch_size
        self.logger = logging.getLogger(f"BatchInserter_{table_name}")

    def insert_batch(self, data: List[Tuple], max_retries: int = 3) -> Dict[str, Any]:
        """插入单个批次，带重试机制"""
        if not data:
            return {'success': 0, 'total': 0, 'time': 0}

        start_time = time.time()
        last_error = None

        for attempt in range(max_retries):
            try:
                # executemany
                affected = self.mysql_common.executemany(
                    self.insert_query,
                    data,
                    self.batch_size
                )

                elapsed = time.time() - start_time
                speed = len(data) / elapsed if elapsed > 0 else 0

                return {
                    'success': affected,
                    'total': len(data),
                    'time': elapsed,
                    'speed': speed
                }

            except Exception as e:
                last_error = e
                self.logger.error(f"批量插入失败 (尝试 {attempt + 1}/{max_retries}): {e}")

                if attempt < max_retries - 1:
                    # 等待后重试
                    wait_time = (attempt + 1) * 2  # 指数退避
                    time.sleep(wait_time)
                    continue

        # 所有重试都失败
        elapsed = time.time() - start_time
        self.logger.error(f"批量插入最终失败: {last_error}")
        return {
            'success': 0,
            'total': len(data),
            'time': elapsed,
            'error': str(last_error)
        }


# ============================================================================
# 分表处理器
# ============================================================================

class TableSuffixProcessor:
    """分表处理器，处理特定分表后缀的税号"""

    def __init__(self, db_config: Dict[str, Any], table_suffix: str):
        self.db_config = db_config
        self.table_suffix = table_suffix

        # 定义表名
        self.table_names = {
            'tax_change': f"tax_change_{table_suffix}",
            'agent_declaration_user': f"agent_declaration_user_{table_suffix}",
            'agent_declaration_salary_wages_info': f"agent_declaration_salary_wages_info_{table_suffix}"
        }

        # 为每个表创建独立的连接池
        self.table_mysql_pools = {}
        for table_key, table_name in self.table_names.items():
            self.table_mysql_pools[table_key] = OptimizedMySQLCommon(
                **db_config,
                pool_size=5,  # 每个表5个连接
                pool_name=f"{table_key}_{table_suffix}"
            )

        # 构建INSERT语句
        self.insert_queries = self._build_insert_queries()

        # 插入器缓存
        self.inserters = {}

        print(f"✅ 初始化分表处理器 {table_suffix}，表名: {self.table_names}")

    def _build_insert_queries(self) -> Dict[str, str]:
        """构建INSERT语句"""
        queries = {}

        # tax_change表
        queries['tax_change'] = """
        INSERT INTO {table_name} 
        (id, belong_tax_no, customer_tax_no, declaration_period, department_id, 
        personal_tax_form_type, type, id_card_no, month_taxable_income_total, 
        calculate_tax_declaration, current_tax_declaration, current_tax_difference, 
        pay_tax_declaration, pay_tax_difference, reconciliation_type, reconciliation_time, 
        income_tag, reconciliation_status, edit_user_id, edit_user_name, ezone_shard_info, 
        created_at, updated_at, drc_check_time) 
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """.format(table_name=self.table_names['tax_change'])

        # agent_declaration_user表 - 修正字段数量问题
        queries['agent_declaration_user'] = """
        INSERT INTO {table_name} 
        (id, user_id, belong_tax_no, customer_tax_no, customer_name, department_no, 
        name, tag, mobile, region, id_card_type, id_card_no, other_id_card_type, 
        other_id_card_no, english_name, tax_identify_number, status, declare_status, 
        declare_fail_reason, verify_status, verify_fail_reason, sex, nationality, 
        birth_country, birthday, education, is_disability, is_martyr_families, 
        is_lonely_old, disability_card_type, disability_card_no, martyr_families_card_no, 
        remark, employment_type, employment_date, tax_related_matters, first_entry_time, 
        expected_departure_time, employment_annual_situation, other_situation_explanation, 
        resignation_date, duty, job_no, staff_id, is_deduct_expense, email, 
        frequent_residence_province, frequent_residence_province_code, frequent_residence_city, 
        frequent_residence_city_code, frequent_residence_area, frequent_residence_area_code, 
        frequent_residence_street, frequent_residence_street_code, frequent_residence_detail, 
        contact_address_province, contact_address_province_code, contact_address_city, 
        contact_address_city_code, contact_address_area, contact_address_area_code, 
        contact_address_street, contact_address_street_code, contact_address_detail, 
        registered_residence_province, registered_residence_province_code, registered_residence_city, 
        registered_residence_city_code, registered_residence_area, registered_residence_area_code, 
        registered_residence_street, registered_residence_street_code, registered_residence_detail, 
        seller_bank_code, seller_bank_province_code, seller_bank_number, 
        personal_investment_amount, personal_investment_percentage, individual_file_no, 
        additional_download_time, update_time, create_time, uuid, data_source, 
        seller_bank_name)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """.format(table_name=self.table_names['agent_declaration_user'])

        # agent_declaration_salary_wages_info表
        queries['agent_declaration_salary_wages_info'] = """
        INSERT INTO {table_name} 
        (id, declaration_id, belong_tax_no, customer_tax_no, declaration_period, 
        personal_tax_form_type, type, obtained_project_code, obtained_project_name, 
        declare_method, is_provide_property_origin_value_proof, property_origin_value, 
        investment_deduction, lottery_type, lottery_name, lottery_issue_number, 
        tax_calculation_ration_reduce, exhibition_cost, name, id_card_no, 
        positive_calculation_mark, individual_file_no, income, tax_exempt_income, 
        deduction_cost, net_salary, cost, pension_insurance_personal, pension_insurance_company, 
        medical_insurance_personal, medical_insurance_company, unemployment_insurance_personal, 
        unemployment_insurance_company, employment_injury_insurance_personal, 
        employment_injury_insurance_company, maternity_insurance_personal, 
        maternity_insurance_company, accumulation_fund_personal, accumulation_fund_company, 
        total_deductions, enterprise_annuity, commercial_health_insurance, 
        tax_deferred_pension_insurance, other, labor_applicable_other, 
        donation_amount_allowed_for_deduction, tax_savings, remark, total_other_deductions, 
        expenditure_children_education, caring_elderly, housing_loan_interest, 
        housing_rent, continuing_education, care_children_under_three_years_old, 
        total_special_additional_deduction, accumulated_income, accumulated_tax_declaration, 
        accumulated_personal_pension, allowable_tax_deductions, accumulated_cost, 
        accumulated_tax_exempt_income, accumulated_deduction_expenses, 
        accumulated_special_deductions, accumulated_other_deductions, 
        accumulated_donation_amount_allowed_for_deduction, accumulated_special_additional_deductions, 
        accumulated_expenditure_children_education, accumulated_caring_elderly, 
        accumulated_housing_loan_interest, accumulated_housing_rent, 
        accumulated_continuing_education, accumulated_care_children_under_three_years_old, 
        accumulated_taxable_income, tax_rate, quick_calculation_deduction, 
        accumulated_taxable_amount, accumulated_tax_reductions_exemptions, 
        accumulated_withholding_tax_amount, accumulated_paid_tax_amount, 
        tax_declaration, update_time, create_time, accumulated_income_amount, declare_flag) 
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
               %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """.format(table_name=self.table_names['agent_declaration_salary_wages_info'])

        return queries

    def _generate_user_table_data(self, persons: List[Dict], start_id: int) -> List[Tuple]:
        """生成用户表数据"""
        data = []

        for i, person in enumerate(persons):
            record = (
                start_id + i,  # id
                person['user_id'],  # user_id
                person['belong_tax_no'],  # belong_tax_no
                person['customer_tax_no'],  # customer_tax_no
                person['customer_name'],  # customer_name
                '',  # department_no
                person['name'],  # name
                '',  # tag
                person['mobile'],  # mobile
                '0',  # region (境内)
                '01',  # id_card_type (居民身份证)
                person['id_card_no'],  # id_card_no
                '',  # other_id_card_type
                '',  # other_id_card_no
                '',  # english_name
                '',  # tax_identify_number
                0,  # status (在职)
                0,  # declare_status
                '',  # declare_fail_reason
                1,  # verify_status (验证通过)
                '',  # verify_fail_reason
                person['sex'],  # sex
                person['nationality'],  # nationality
                '',  # birth_country
                person['birthday'],  # birthday
                person['education'],  # education
                0,  # is_disability
                0,  # is_martyr_families
                0,  # is_lonely_old
                '',  # disability_card_type
                '',  # disability_card_no
                '',  # martyr_families_card_no
                '',  # remark
                30,  # employment_type (雇员)
                person['current_time'],  # employment_date
                '平台内从业人员',  # tax_related_matters
                '',  # first_entry_time
                '',  # expected_departure_time
                '',  # employment_annual_situation
                '',  # other_situation_explanation
                None,  # resignation_date
                '普通',  # duty
                f'EMP{start_id + i:08d}',  # job_no
                person['id_card_no'],  # staff_id
                1,  # is_deduct_expense
                f'{person["name"]}@test.com',  # email
                '', '', '', '', '', '', '', '', '',  # 居住地相关
                '', '', '', '', '', '', '', '', '',  # 联系地址相关
                '', '', '', '', '', '', '', '', '',  # 户籍地相关
                '', '', '',  # 银行信息
                0.00,  # personal_investment_amount
                0.0000,  # personal_investment_percentage
                person['id_card_no'],  # individual_file_no
                0,  # additional_download_time
                person['current_time'],  # update_time
                person['current_time'],  # create_time
                str(uuid.uuid4()),  # uuid
                '脚本生成'  # data_source
            )
            data.append(record)

        return data

    def _generate_salary_table_data(self, persons: List[Dict], start_id: int) -> List[Tuple]:
        """生成薪资表数据"""
        data = []

        for i, person in enumerate(persons):
            record = (
                start_id + i,  # id
                person['declaration_id'],  # declaration_id
                person['belong_tax_no'],  # belong_tax_no
                person['customer_tax_no'],  # customer_tax_no
                person['declaration_period'],  # declaration_period
                0,  # personal_tax_form_type (综合所得)
                2,  # type (劳务报酬适用累计预扣法)
                '0489',  # obtained_project_code
                '其他连续劳务报酬',  # obtained_project_name
                0,  # declare_method
                0,  # is_provide_property_origin_value_proof
                0.00,  # property_origin_value
                0.00,  # investment_deduction
                0,  # lottery_type
                '',  # lottery_name
                '',  # lottery_issue_number
                0.00,  # tax_calculation_ration_reduce
                0.00,  # exhibition_cost
                person['name'],  # name
                person['id_card_no'],  # id_card_no
                0,  # positive_calculation_mark
                '',  # individual_file_no
                person['income'],  # income
                0.00,  # tax_exempt_income
                person['deduction_cost'],  # deduction_cost
                person['income'],  # net_salary
                person['cost'],  # cost
                0.00,  # pension_insurance_personal
                0.00,  # pension_insurance_company
                0.00,  # medical_insurance_personal
                0.00,  # medical_insurance_company
                0.00,  # unemployment_insurance_personal
                0.00,  # unemployment_insurance_company
                0.00,  # employment_injury_insurance_personal
                0.00,  # employment_injury_insurance_company
                0.00,  # maternity_insurance_personal
                0.00,  # maternity_insurance_company
                0.00,  # accumulation_fund_personal
                0.00,  # accumulation_fund_company
                0.00,  # total_deductions
                0.00,  # enterprise_annuity
                0.00,  # commercial_health_insurance
                0.00,  # tax_deferred_pension_insurance
                0.00,  # other
                0.00,  # labor_applicable_other
                0.00,  # donation_amount_allowed_for_deduction
                0.00,  # tax_savings
                '',  # remark
                0.00,  # total_other_deductions
                0.00,  # expenditure_children_education
                0.00,  # caring_elderly
                0.00,  # housing_loan_interest
                0.00,  # housing_rent
                0.00,  # continuing_education
                0.00,  # care_children_under_three_years_old
                0.00,  # total_special_additional_deduction
                person['income'],  # accumulated_income
                0.00,  # accumulated_tax_declaration
                0.00,  # accumulated_personal_pension
                person['cost'],  # allowable_tax_deductions
                person['cost'],  # accumulated_cost
                0.00,  # accumulated_tax_exempt_income
                person['deduction_cost'],  # accumulated_deduction_expenses
                0.00,  # accumulated_special_deductions
                0.00,  # accumulated_other_deductions
                0.00,  # accumulated_donation_amount_allowed_for_deduction
                0.00,  # accumulated_special_additional_deductions
                0.00,  # accumulated_expenditure_children_education
                0.00,  # accumulated_caring_elderly
                0.00,  # accumulated_housing_loan_interest
                0.00,  # accumulated_housing_rent
                0.00,  # accumulated_continuing_education
                0.00,  # accumulated_care_children_under_three_years_old
                person['taxable_income'],  # accumulated_taxable_income
                person['tax_rate'],  # tax_rate
                person['quick_deduction'],  # quick_calculation_deduction
                person['tax_amount'],  # accumulated_taxable_amount
                0.00,  # accumulated_tax_reductions_exemptions
                0.00,  # accumulated_withholding_tax_amount
                0.00,  # accumulated_paid_tax_amount
                person['tax_amount'],  # tax_declaration
                person['current_time'],  # update_time
                person['current_time'],  # create_time
                person['income'],  # accumulated_income_amount
                0  # declare_flag
            )
            data.append(record)

        return data

    def _generate_tax_change_data(self, persons: List[Dict], start_id: int) -> List[Tuple]:
        """生成税款变动表数据"""
        data = []

        for i, person in enumerate(persons):
            record = (
                start_id + i,  # id
                person['belong_tax_no'],  # belong_tax_no
                person['customer_tax_no'],  # customer_tax_no
                person['declaration_period'],  # declaration_period
                '',  # department_id
                0,  # personal_tax_form_type
                2,  # type (劳务报酬适用累计预扣法)
                person['id_card_no'],  # id_card_no
                person['income'],  # month_taxable_income_total
                person['tax_amount'],  # calculate_tax_declaration
                0.00,  # current_tax_declaration
                0.00,  # current_tax_difference
                0.00,  # pay_tax_declaration
                0.00,  # pay_tax_difference
                '',  # reconciliation_type
                None,  # reconciliation_time
                None,  # income_tag
                'INIT',  # reconciliation_status
                '',  # edit_user_id
                '',  # edit_user_name
                None,  # ezone_shard_info
                person['current_time'],  # created_at
                person['current_time'],  # updated_at
                person['current_time'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # drc_check_time
            )
            data.append(record)

        return data

    def process_tax_config(self, tax_config: Dict, persons_per_tax: int,
                           start_ids: Dict[str, int], data_generator: DynamicDataGenerator,
                           batch_size: int = 10000) -> Dict[str, Any]:
        """处理单个税号的数据"""
        tax_no = tax_config['customer_tax_no']
        tax_no_index = 0  # 这里可以根据税号在列表中的位置确定索引

        print(f"\n🚀 开始处理税号: {tax_no} (分表: {self.table_suffix})")
        print(f"   目标数据量: {persons_per_tax:,} 人 × 3 张表")
        print(f"   分配的起始ID: tax_change={start_ids['tax_change']:,}, "
              f"user={start_ids['agent_declaration_user']:,}, "
              f"salary={start_ids['agent_declaration_salary_wages_info']:,}")

        total_batches = (persons_per_tax + batch_size - 1) // batch_size

        results = {
            'tax_change': {'total': 0, 'success': 0, 'time': 0},
            'agent_declaration_user': {'total': 0, 'success': 0, 'time': 0},
            'agent_declaration_salary_wages_info': {'total': 0, 'success': 0, 'time': 0}
        }

        # 创建插入器
        inserters = {
            'tax_change': OptimizedBatchInserter(
                self.table_mysql_pools['tax_change'],
                self.table_names['tax_change'],
                self.insert_queries['tax_change'],
                batch_size=5000
            ),
            'agent_declaration_user': OptimizedBatchInserter(
                self.table_mysql_pools['agent_declaration_user'],
                self.table_names['agent_declaration_user'],
                self.insert_queries['agent_declaration_user'],
                batch_size=5000
            ),
            'agent_declaration_salary_wages_info': OptimizedBatchInserter(
                self.table_mysql_pools['agent_declaration_salary_wages_info'],
                self.table_names['agent_declaration_salary_wages_info'],
                self.insert_queries['agent_declaration_salary_wages_info'],
                batch_size=5000
            )
        }

        start_time = time.time()

        # 分批处理
        for batch_num in range(total_batches):
            batch_start = batch_num * batch_size
            current_batch_size = min(batch_size, persons_per_tax - batch_start)

            # 显示进度
            if batch_num % 10 == 0 or batch_num == total_batches - 1:
                print(f"📦 处理批次 {batch_num + 1}/{total_batches} "
                      f"(人员 {batch_start + 1}~{batch_start + current_batch_size})")

            # 生成批次人员数据
            persons = data_generator.generate_person_batch_numpy(
                tax_config, batch_start, current_batch_size, tax_no_index
            )

            # 生成三张表的数据
            user_data = self._generate_user_table_data(
                persons, start_ids['agent_declaration_user'] + batch_start
            )
            salary_data = self._generate_salary_table_data(
                persons, start_ids['agent_declaration_salary_wages_info'] + batch_start
            )
            tax_change_data = self._generate_tax_change_data(
                persons, start_ids['tax_change'] + batch_start
            )

            # 并发插入三张表
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(
                        inserters['agent_declaration_user'].insert_batch,
                        user_data
                    ): 'agent_declaration_user',
                    executor.submit(
                        inserters['agent_declaration_salary_wages_info'].insert_batch,
                        salary_data
                    ): 'agent_declaration_salary_wages_info',
                    executor.submit(
                        inserters['tax_change'].insert_batch,
                        tax_change_data
                    ): 'tax_change'
                }

                # 收集结果
                for future in as_completed(futures):
                    table_key = futures[future]
                    try:
                        result = future.result(timeout=300)

                        results[table_key]['total'] += result.get('total', 0)
                        results[table_key]['success'] += result.get('success', 0)
                        results[table_key]['time'] += result.get('time', 0)

                    except Exception as e:
                        print(f"❌ {table_key} 插入异常: {e}")
                        results[table_key]['total'] += current_batch_size

        total_time = time.time() - start_time

        # 汇总结果
        total_records = sum(results[key]['total'] for key in results)
        total_success = sum(results[key]['success'] for key in results)

        summary = {
            'tax_no': tax_no,
            'table_suffix': self.table_suffix,
            'total_persons': persons_per_tax,
            'total_records': total_records,
            'total_success': total_success,
            'total_time': total_time,
            'avg_speed': total_records / total_time if total_time > 0 else 0,
            'table_results': results
        }

        print(f"\n✅ 税号 {tax_no} 处理完成 (分表: {self.table_suffix})")
        print(f"   总用时: {total_time:.1f}s")
        print(f"   总记录: {total_records:,} 条")
        print(f"   成功: {total_success:,} 条")
        print(f"   速度: {summary['avg_speed']:.1f} 条/秒")

        return summary

    def cleanup(self):
        """清理资源"""
        print(f"🧹 清理分表处理器 {self.table_suffix} 的资源...")

        # 关闭所有连接池
        for key, pool in self.table_mysql_pools.items():
            try:
                pool.close_all()
            except:
                pass

        print(f"✅ 分表处理器 {self.table_suffix} 资源清理完成")


# ============================================================================
# 主程序
# ============================================================================

class ThreeTableBatchProcessor:
    """批量处理器"""

    def __init__(self, db_config: Dict[str, Any]):
        self.db_config = db_config

        # 创建主连接（用于查询配置）
        self.main_mysql = OptimizedMySQLCommon(
            **db_config,
            pool_size=5,
            pool_name="main"
        )

        # 数据生成器
        self.data_generator = DynamicDataGenerator(self.main_mysql)

        # 分表处理器缓存
        self.table_processors = {}

    def get_table_processor(self, table_suffix: str) -> TableSuffixProcessor:
        """获取或创建分表处理器"""
        if table_suffix not in self.table_processors:
            print(f"🔄 创建分表处理器 {table_suffix}")
            self.table_processors[table_suffix] = TableSuffixProcessor(self.db_config, table_suffix)

        return self.table_processors[table_suffix]

    def process_all_tax_configs(self, persons_per_tax: int = 600000,
                                concurrent_tax: int = 17):
        """处理所有税号配置"""
        print("=" * 80)
        print("🚀 开始批量处理多个税号")
        print("=" * 80)

        # 1. 获取税号配置
        tax_configs = self.data_generator.get_tax_configs()

        if not tax_configs:
            print("❌ 未获取到税号配置，程序退出")
            return

        # 2. 获取税号列表
        tax_nos = [config['customer_tax_no'] for config in tax_configs]

        # 3. 获取分表后缀映射
        table_suffix_mapping = self.data_generator.get_table_suffix_mapping(tax_nos)

        # 4. 将税号配置按分表分组
        tax_configs_by_suffix = {}
        for tax_config in tax_configs:
            tax_no = tax_config['customer_tax_no']
            table_suffix = table_suffix_mapping.get(tax_no, "101")

            if table_suffix not in tax_configs_by_suffix:
                tax_configs_by_suffix[table_suffix] = []

            # 添加分表后缀到配置中
            tax_config['table_suffix'] = table_suffix
            tax_configs_by_suffix[table_suffix].append(tax_config)

        print(f"\n📋 分表分组结果:")
        for table_suffix, configs in tax_configs_by_suffix.items():
            print(f"   分表 {table_suffix}: {len(configs)} 个税号")
            for config in configs:
                print(f"     - {config['customer_tax_no']}")

        # 5. 为每个分表获取最大ID
        max_ids_by_suffix = {}
        for table_suffix in tax_configs_by_suffix.keys():
            max_ids_by_suffix[table_suffix] = self.data_generator.get_max_ids_for_suffix(table_suffix)

        # 6. 为每个分表的每个税号分配ID范围
        tax_configs_with_start_ids = []
        for table_suffix, configs in tax_configs_by_suffix.items():
            max_ids = max_ids_by_suffix[table_suffix]

            for i, tax_config in enumerate(configs):
                # 每个税号获得独立的ID范围，避免冲突
                start_ids_for_tax = {
                    'tax_change': max_ids['tax_change'] + 1 + (i * persons_per_tax),
                    'agent_declaration_user': max_ids['agent_declaration_user'] + 1 + (i * persons_per_tax),
                    'agent_declaration_salary_wages_info': max_ids['agent_declaration_salary_wages_info'] + 1 + (
                                i * persons_per_tax)
                }
                tax_configs_with_start_ids.append((tax_config, start_ids_for_tax))
                print(f"📊 税号 {tax_config['customer_tax_no']} (分表: {table_suffix}) 分配的ID范围: "
                      f"tax_change={start_ids_for_tax['tax_change']:,}, "
                      f"user={start_ids_for_tax['agent_declaration_user']:,}, "
                      f"salary={start_ids_for_tax['agent_declaration_salary_wages_info']:,}")

        total_tax_configs = len(tax_configs)

        print(f"\n📋 处理计划:")
        print(f"   税号数量: {total_tax_configs}")
        print(f"   分表数量: {len(tax_configs_by_suffix)}")
        print(f"   每个税号: {persons_per_tax:,} 人")
        print(f"   并发税号数: {concurrent_tax}")
        print(f"   预估总数据量: {total_tax_configs * persons_per_tax * 3:,} 条")

        all_results = []
        total_start_time = time.time()

        # 7. 并发处理税号
        with ThreadPoolExecutor(max_workers=concurrent_tax) as executor:
            # 提交所有税号任务
            future_to_tax = {}
            for tax_config, start_ids_for_tax in tax_configs_with_start_ids:
                table_suffix = tax_config['table_suffix']
                table_processor = self.get_table_processor(table_suffix)

                future = executor.submit(
                    table_processor.process_tax_config,
                    tax_config,
                    persons_per_tax,
                    start_ids_for_tax,
                    self.data_generator,
                    10000  # 批次大小
                )
                future_to_tax[future] = (tax_config['customer_tax_no'], table_suffix)

            # 收集结果
            completed = 0
            for future in as_completed(future_to_tax):
                tax_no, table_suffix = future_to_tax[future]
                completed += 1

                try:
                    result = future.result(timeout=3600 * 6)  # 6小时超时
                    all_results.append(result)

                    print(f"\n✅ [{completed}/{total_tax_configs}] 税号 {tax_no} 处理完成 (分表: {table_suffix})")

                except Exception as e:
                    print(f"\n❌ [{completed}/{total_tax_configs}] 税号 {tax_no} 处理失败: {e}")

        total_time = time.time() - total_start_time

        # 8. 生成最终报告
        self.generate_final_report(all_results, total_time)

        # 9. 清理资源
        self.cleanup()

        return all_results

    def generate_final_report(self, all_results: List[Dict], total_time: float):
        """生成最终报告"""
        print("\n" + "=" * 80)
        print("📊 批量插入任务完成总结")
        print("=" * 80)

        total_persons = 0
        total_records = 0
        total_success = 0

        table_totals = {
            'tax_change': {'total': 0, 'success': 0},
            'agent_declaration_user': {'total': 0, 'success': 0},
            'agent_declaration_salary_wages_info': {'total': 0, 'success': 0}
        }

        # 按分表统计
        results_by_suffix = {}

        for result in all_results:
            total_persons += result['total_persons']
            total_records += result['total_records']
            total_success += result['total_success']

            # 按分表分组
            table_suffix = result['table_suffix']
            if table_suffix not in results_by_suffix:
                results_by_suffix[table_suffix] = []
            results_by_suffix[table_suffix].append(result)

            for table_key in table_totals:
                if table_key in result['table_results']:
                    table_totals[table_key]['total'] += result['table_results'][table_key]['total']
                    table_totals[table_key]['success'] += result['table_results'][table_key]['success']

        overall_speed = total_records / total_time if total_time > 0 else 0

        print(f"📋 总体统计:")
        print(f"   总税号数: {len(all_results)}")
        print(f"   总分表数: {len(results_by_suffix)}")
        print(f"   总人数: {total_persons:,}")
        print(f"   总记录数: {total_records:,}")
        print(f"   总成功数: {total_success:,}")
        if total_records > 0:
            print(f"   总成功率: {total_success / total_records * 100:.2f}%")
        print(f"   总执行时间: {total_time:.1f}秒 ({total_time / 60:.1f}分钟)")
        print(f"   整体平均速度: {overall_speed:.1f} 条/秒")

        print(f"\n📋 按分表统计:")
        for table_suffix, results in results_by_suffix.items():
            suffix_persons = sum(r['total_persons'] for r in results)
            suffix_records = sum(r['total_records'] for r in results)
            suffix_success = sum(r['total_success'] for r in results)
            suffix_success_rate = suffix_success / suffix_records * 100 if suffix_records > 0 else 0

            print(f"   分表 {table_suffix}:")
            print(f"     税号数: {len(results)}")
            print(f"     人数: {suffix_persons:,}")
            print(f"     记录数: {suffix_records:,}")
            print(f"     成功数: {suffix_success:,} ({suffix_success_rate:.2f}%)")

        print(f"\n📋 按表统计:")
        for table_key, stats in table_totals.items():
            if stats['total'] > 0:
                success_rate = stats['success'] / stats['total'] * 100
                print(f"   {table_key}: "
                      f"{stats['success']:,}/{stats['total']:,} ({success_rate:.1f}%)")

        if overall_speed > 0:
            estimated_10m = 10000000 / overall_speed
            print(f"\n⏱️  性能预估:")
            print(f"   1000万条数据预计耗时: {estimated_10m:.0f}秒 ({estimated_10m / 60:.1f}分钟)")

    def cleanup(self):
        """清理资源"""
        print("\n🧹 清理资源...")

        # 关闭所有分表处理器
        for table_suffix, processor in self.table_processors.items():
            try:
                processor.cleanup()
            except:
                pass

        try:
            self.main_mysql.close_all()
        except:
            pass

        print("✅ 资源清理完成")


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主程序"""
    # 数据库配置
    db_config = {
        'host': '172.28.30.59',
        'user': 'qingyun',
        'password': 'QY20Lsf%!PLfM25Ts!',
        'database': 'declaration-qingyun-test',
        'port': 3306,
        'autocommit': False,
        'charset': 'utf8mb4',
        'connect_timeout': 10
    }

    print("=" * 80)
    print("🎯 批量插入数据 - 雪糕版 (支持多分表)")
    print("=" * 80)

    try:
        # 创建处理器
        processor = ThreeTableBatchProcessor(db_config)

        # 设置参数
        persons_per_tax = 600000  # 每个税号60万人
        concurrent_tax = 10  # 同时处理17个税号

        # 开始批量处理
        results = processor.process_all_tax_configs(persons_per_tax, concurrent_tax)

        print("\n" + "=" * 80)
        print("🎉 所有批量插入任务执行完成!")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n⚠️ 用户中断执行")
    except Exception as e:
        print(f"\n❌ 程序执行异常: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 设置随机种子以确保可重复性
    np.random.seed(42)
    random.seed(42)

    # 设置日志级别
    logging.basicConfig(
        level=logging.WARNING,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    main()