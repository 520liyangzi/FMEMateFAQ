import unittest

from fmemate.matcher import recommend, split_requirements


def function(fid, zh, en, objects):
    return {"id": fid, "question_zh": zh, "question_en": en,
            "sources": [{"sheet": "能力", "row": 2}], "objects": objects}


def obj(zh, en, fields):
    return {"id": zh, "name_zh": zh, "name_en": en,
            "sources": [{"sheet": "能力", "row": 3}],
            "fields": [{"id": str(i), "name_zh": a, "name_en": b,
                        "sources": [{"sheet": "能力", "row": i + 4}]} for i, (a, b) in enumerate(fields)]}


def catalog():
    return {"functions": [
        function("ticket", "请帮我分析一下这个工单", "Help me analyze this ticket", [
            obj("故障端口表", "Fault Port Table", [("接收光功率", "Receive Optical Power"), ("发射光功率", "Transmit Optical Power")]),
            obj("时钟信息", "Clock Information", [("GNSS工作模式", "GNSS Working Mode")])]),
        function("power", "查询光功率", "Query the optical power", [
            obj("端口信息", "Port Information", [("接收光功率", "Rx Power"), ("发射光功率", "Tx Power")])]),
        function("hardware", "查询单板信息", "Query board information", [
            obj("单板信息", "Board Information", [("柜号", "Cabinet Number"), ("框号", "Frame Number"), ("槽号", "Slot Number"), ("发射端口号", "Transmit Port Number"), ("驻波比", "VSWR"), ("告警门限", "Alarm Threshold")])]),
        function("fan", "查询风扇", "Query fan", [obj("风扇信息", "Fan Information", [("风扇转速", "Fan Speed")])]),
    ]}


class MatcherTests(unittest.TestCase):
    def test_user_example_is_one_function(self):
        result = recommend(catalog(), "我想查 端口的收发光功率和GNSS工作模式")
        self.assertEqual(len(result["requirements"]), 3)
        self.assertEqual(result["plan"]["function_ids"], ["ticket"])
        self.assertEqual(result["plan"]["coverage"], 1)
        self.assertTrue(result["plan"]["optimal"])
        evidence = result["recommendations"][0]["evidence"]
        self.assertEqual([e["field_zh"] for e in evidence], ["接收光功率", "发射光功率", "GNSS工作模式"])
        self.assertEqual(evidence[0]["source"]["sheet"], "能力")

    def test_common_language_variants(self):
        cases = ["帮我查下端口的收发光功率和GNSS工作模式", "想知道收发光功率和GNSS工作模式", "接收光功率/GNSS工作模式", "rx and tx optical power"]
        for query in cases:
            with self.subTest(query=query):
                result = recommend(catalog(), query)
                self.assertEqual(result["plan"]["coverage"], 1)

    def test_rf_power_is_not_optical_power(self):
        for query in ["发射功率", "接收功率"]:
            with self.subTest(query=query):
                result = recommend(catalog(), query)
                self.assertEqual(result["plan"]["coverage"], 0)

    def test_more_than_limit_not_silently_truncated(self):
        with self.assertRaises(ValueError):
            recommend(catalog(), "和".join("未知" + str(i) for i in range(25)))

    def test_english_aliases(self):
        result = recommend(catalog(), "Please check port rx/tx optical power and GNSS operating mode")
        self.assertEqual(result["plan"]["function_ids"], ["ticket"])
        self.assertEqual(result["plan"]["coverage"], 1)

    def test_compound_unknown_retained(self):
        result = recommend(catalog(), "收光功率和火星温度")
        self.assertEqual(result["plan"]["coverage"], 0.5)
        self.assertEqual(result["unmatched_requirements"][0]["text"], "火星温度")
        self.assertTrue(all(c["coverage"] < 1 for c in result["recommendations"]))

    def test_port_does_not_match_transport(self):
        test_catalog = {"functions": [function("a", "传输分析", "Transport Analysis", [obj("传输", "Transport", [("温度", "Temperature")])])]}
        result = recommend(test_catalog, "port")
        self.assertEqual(result["recommendations"], [])

    def test_optical_power_not_transmit_port_number(self):
        result = recommend({"functions": [catalog()["functions"][2]]}, "发射光功率")
        self.assertEqual(result["plan"]["coverage"], 0)

    def test_gnss_mode_not_gnss_status(self):
        test_catalog = {"functions": [function("a", "GNSS状态", "GNSS status", [obj("时钟", "Clock", [("GNSS状态", "GNSS Status")])])]}
        result = recommend(test_catalog, "GNSS工作模式")
        self.assertEqual(result["plan"]["coverage"], 0)

    def test_all_unknown(self):
        result = recommend(catalog(), "火星天气和存款余额")
        self.assertEqual(result["plan"]["coverage"], 0)
        self.assertEqual(len(result["unmatched_requirements"]), 2)
        self.assertEqual(result["recommendations"], [])

    def test_multiple_function_plan(self):
        result = recommend(catalog(), "收发光功率和风扇转速")
        self.assertEqual(set(result["plan"]["function_ids"]), {"power", "fan"})
        self.assertEqual(result["plan"]["coverage"], 1)

    def test_exact_plan_beats_greedy(self):
        field_names = ["参数甲", "参数乙", "参数丙", "参数丁", "参数戊", "参数己"]
        def fn(fid, indices):
            return function(fid, fid, fid, [obj("表", "Table", [(field_names[i], "") for i in indices])])
        test_catalog = {"functions": [fn("largest", [0, 1, 2, 3]), fn("left", [0, 1, 4]), fn("right", [2, 3, 5])]}
        result = recommend(test_catalog, "和".join(field_names))
        self.assertEqual(set(result["plan"]["function_ids"]), {"left", "right"})
        self.assertTrue(result["plan"]["optimal"])

    def test_object_only_match_does_not_claim_irrelevant_field(self):
        test_catalog = {"functions": [function("a", "查询端口", "Query port", [obj("光功率", "Optical Power", [("柜号", "Cabinet Number")])])]}
        result = recommend(test_catalog, "光功率")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["level"], "object")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["field_zh"], "")

    def test_object_context_with_short_field(self):
        test_catalog = {"functions": [function("a", "查询时钟", "Query clock", [obj("GNSS信息", "GNSS Information", [("工作模式", "Working Mode")])])]}
        result = recommend(test_catalog, "GNSS工作模式")
        self.assertEqual(result["plan"]["function_ids"], ["a"])
        self.assertEqual(result["recommendations"][0]["evidence"][0]["field_zh"], "工作模式")

    def test_direct_question(self):
        result = recommend(catalog(), "Help me analyze this ticket")
        self.assertEqual(result["plan"]["function_ids"], ["ticket"])
        self.assertEqual(result["recommendations"][0]["evidence"][0]["level"], "question")

    def test_unknown_modifier_not_discarded(self):
        result = recommend(catalog(), "火星的接收光功率")
        self.assertEqual(result["plan"]["coverage"], 0)

    def test_dynamic_imported_label(self):
        test_catalog = {"functions": [function("a", "查其他信息", "Query information", [obj("设备信息", "Device Information", [("电源输出电压", "Power Output Voltage")])])]}
        result = recommend(test_catalog, "我想查一下设备的电源输出电压")
        self.assertEqual(result["plan"]["function_ids"], ["a"])

    def test_gnss_spaces_and_possessive(self):
        for query in ["GNSS 工作模式", "GNSS的工作模式"]:
            with self.subTest(query=query):
                result = recommend(catalog(), query)
                self.assertEqual(result["plan"]["function_ids"], ["ticket"])

    def test_overrides(self):
        result = recommend(catalog(), "自然语言复杂表达", requirements=["收光功率", "GNSS工作模式"])
        self.assertEqual(result["plan"]["coverage"], 1)

    def test_empty_and_long_query(self):
        for query in ["", " ", "x" * 4001]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                recommend(catalog(), query)

    def test_generic_optical_power(self):
        result = recommend(catalog(), "端口光功率")
        self.assertEqual(result["plan"]["coverage"], 1)

    def test_non_alias_english_case(self):
        test_catalog = {"functions": [function("a", "查其他信息", "Query information", [obj("设备", "Device", [("电源输出电压", "Power Output Voltage")])])]}
        result = recommend(test_catalog, "please show me the POWER OUTPUT VOLTAGE")
        self.assertEqual(result["plan"]["coverage"], 1)


if __name__ == "__main__":
    unittest.main()
