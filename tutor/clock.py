"""시계 한 곳: 지금 시각과 '오늘' 은 모두 여기서만 얻는다(복습 날짜·연속 공부 일수·오늘의 공부).

날짜는 정수 '일 번호'(date.toordinal)로 다룬다. 테스트와 화면 점검은 set_offset 으로 시계를 앞당긴다.
화면 점검용 서버만 환경변수 TUTOR_TEST_CLOCK=1 일 때 POST /api/test/clock 으로 앞당길 수 있고, 평소 서버는 이 길이 닫혀 있다.
"""
import os
import time
from datetime import date, datetime

_offset_days = 0


def test_clock_enabled():
    return os.environ.get("TUTOR_TEST_CLOCK") == "1"


def set_offset(days):
    """시계를 days 일만큼 앞당긴다(0 이면 원래대로)."""
    global _offset_days
    _offset_days = int(days)


def offset():
    return _offset_days


def now():
    return time.time() + _offset_days * 86400


def day_of(ts):
    """시각(epoch 초) → 그날의 일 번호(로컬 날짜)."""
    return datetime.fromtimestamp(ts).date().toordinal()


def today():
    return day_of(now())


def iso(day):
    """일 번호 → '2026-11-20'."""
    return date.fromordinal(day).isoformat()
