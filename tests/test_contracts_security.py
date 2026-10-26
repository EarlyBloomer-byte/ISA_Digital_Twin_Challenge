import json
import time

import pytest
from pydantic import ValidationError

from routetwin.contracts import Batch
from routetwin.security import IngestVerifier, sign

GOOD = {"messages": [
    {"type": "segment_obs", "ts": 1.0, "source": "s", "segment_id": 0, "direction": 0, "window_s": 600,
     "vehicle_count": 10, "truck_count": 2, "mean_speed_kmh": 60},
    {"type": "probe_obs", "ts": 1.0, "source": "p", "segment_id": 0, "vehicle_id": "A", "iri_m_per_km": 3.0, "speed_kmh": 50},
]}


def test_batch_parses_discriminated_union():
    b = Batch.model_validate(GOOD)
    assert [m.type for m in b.messages] == ["segment_obs", "probe_obs"]


@pytest.mark.parametrize("patch", [
    {"mean_speed_kmh": -5}, {"direction": 2}, {"segment_id": -1}, {"vehicle_count": "many"}])
def test_invalid_values_rejected(patch):
    bad = json.loads(json.dumps(GOOD))
    bad["messages"][0].update(patch)
    with pytest.raises(ValidationError):
        Batch.model_validate(bad)


def test_unknown_message_type_rejected():
    with pytest.raises(ValidationError):
        Batch.model_validate({"messages": [{"type": "nope", "ts": 1, "source": "x"}]})


def test_signature_accepts_valid_and_blocks_replay():
    v = IngestVerifier("k")
    body, ts = b'{"messages": []}', str(time.time())
    sig = sign("k", ts, body)
    assert v.verify(ts, sig, body) == (True, "ok")
    assert v.verify(ts, sig, body) == (False, "replay")


def test_signature_rejects_tamper_wrong_key_and_stale():
    v = IngestVerifier("k")
    body, ts = b"{}", str(time.time())
    assert v.verify(ts, sign("k", ts, body), b"{ }")[1] == "bad_signature"
    assert v.verify(ts, sign("other", ts, body), body)[1] == "bad_signature"
    old = str(time.time() - 3600)
    assert v.verify(old, sign("k", old, body), body)[1] == "stale_timestamp"
    assert v.verify("abc", "x", body)[1] == "bad_timestamp"
