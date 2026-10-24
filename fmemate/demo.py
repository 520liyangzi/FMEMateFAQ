"""Synthetic examples only. These are not an authoritative product catalog."""


def demo_catalog():
    def field(key, zh, en, row):
        return {"id": key, "name_zh": zh, "name_en": en,
                "sources": [{"sheet": "演示数据", "row": row}]}

    def obj(key, zh, en, fields):
        return {"id": key, "name_zh": zh, "name_en": en, "fields": fields,
                "sources": fields[0]["sources"] if fields else []}

    optical = obj("demo_ports", "故障端口表", "Faulty port table", [
        field("demo_rx", "接收光功率", "Receive Optical Power", 2),
        field("demo_tx", "发射光功率", "Transmit Optical Power", 3),
        field("demo_cabinet", "柜号", "Cabinet Number", 4),
        field("demo_frame", "框号", "Frame Number", 5),
        field("demo_slot", "槽号", "Slot Number", 6),
        field("demo_port", "发射端口号", "Transmit Port Number", 7),
    ])
    gnss = obj("demo_gnss", "GNSS 信息", "GNSS information", [
        field("demo_gnss_mode", "GNSS工作模式", "GNSS Working Mode", 8),
    ])
    topology = obj("demo_topology", "拓扑图", "Topology", [
        field("demo_fault_path", "故障链路", "Fault Path", 9),
    ])
    alarms = obj("demo_alarms", "告警列表", "Alarm list", [
        field("demo_alarm_name", "告警名称", "Alarm Name", 12),
        field("demo_alarm_threshold", "告警门限", "Alarm Threshold", 13),
    ])

    def fn(key, zh, en, objects):
        return {"id": key, "question_zh": zh, "question_en": en,
                "objects": objects, "sources": objects[0]["sources"]}

    return {"functions": [
        fn("demo_analyze", "请帮我分析一下这个工单", "Help me analyze this ticket",
           [optical, gnss, topology]),
        fn("demo_power", "查询端口光功率", "Query the optical power", [optical]),
        fn("demo_gnss_query", "查询 GNSS 工作模式", "Query the GNSS working mode", [gnss]),
        fn("demo_alarm_query", "还有其他告警吗？", "Any other alarms?", [alarms]),
    ], "metadata": {"filename": "内置演示数据", "is_demo": True,
                    "notice": "仅用于演示推荐逻辑，真实功能以你导入的 Excel 为准。"}}
