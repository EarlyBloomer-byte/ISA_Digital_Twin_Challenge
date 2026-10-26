from routetwin.alarms import AlarmDef, AlarmManager

DEF = AlarmDef("T", "high", 2, "msg", "cons", "act")


def feed(m, ts, raise_cond, clear_cond, **kw):
    m.evaluate("S01.T", DEF, 0, ts, raise_cond, clear_cond, **kw)


def test_on_delay_blocks_single_spike():
    m = AlarmManager()
    feed(m, 1, True, False)
    feed(m, 2, False, True)
    feed(m, 3, True, False)
    assert not m.active
    feed(m, 4, True, False)
    assert "S01.T" in m.active


def test_deadband_prevents_chatter_and_lifecycle():
    m = AlarmManager()
    for t in (1, 2):
        feed(m, t, True, False)
    a = m.active["S01.T"]
    assert a.state == "active_unack"
    feed(m, 3, False, False)             # inside deadband: stays active
    assert a.state == "active_unack"
    assert m.acknowledge(a.id, 4) and a.state == "active_ack"
    feed(m, 5, False, True)              # cleared after ack: archived
    assert "S01.T" not in m.active and len(m.history) == 1


def test_return_to_normal_unacknowledged_then_ack():
    m = AlarmManager()
    for t in (1, 2):
        feed(m, t, True, False)
    feed(m, 3, False, True)
    a = m.active["S01.T"]
    assert a.state == "rtn_unack"
    m.acknowledge(a.id, 4)
    assert "S01.T" not in m.active


def test_suppression_removes_child_alarm():
    m = AlarmManager()
    for t in (1, 2):
        feed(m, t, True, False)
    feed(m, 3, True, False, suppressed=True)
    assert "S01.T" not in m.active


def test_flood_kpi():
    m = AlarmManager()
    ev = AlarmDef("E", "medium", 1, "m", "c", "a")
    for i in range(12):
        m.raise_event(f"S01.E{i}", ev, 0, 100.0 + i)
    k = m.kpis(120.0)
    assert k["rate_per_10min"] == 12 and k["flood_now"] and k["flood_events"] == 1


def test_auto_archive_option():
    m = AlarmManager(auto_archive_rtn_s=100)
    for t in (1, 2):
        feed(m, t, True, False)
    feed(m, 3, False, True)
    m.housekeeping(50)
    assert "S01.T" in m.active
    m.housekeeping(500)
    assert "S01.T" not in m.active
