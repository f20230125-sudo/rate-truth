"""Seeded per-night mock stock and atomic, expiring holds in one process."""

import hashlib
import heapq
from collections import Counter, defaultdict, deque
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from threading import RLock
from uuid import uuid4

from rate_truth.supplier.models import Hotel, RoomType


def stable_int(seed: int, *parts: object) -> int:
    payload = "|".join(str(part) for part in (seed, *parts)).encode()
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


class SoldOut(ValueError):
    pass


class HoldLimit(ValueError):
    def __init__(self, code="hold_rate_limited", status=429):
        super().__init__("mock hold limit reached; retry later")
        self.code, self.status = code, status


class Inventory:
    def __init__(self, seed: int = 2026, clock: Callable[[], datetime] | None = None):
        self.seed = seed
        self.clock = clock or (lambda: datetime.now(UTC))
        self._holds: dict[str, dict] = {}
        self._by_room = defaultdict(set)
        self._by_client = Counter()
        self._by_hotel = Counter()
        self._expires = []
        self._attempts = {}
        self._lock = RLock()

    def stock(self, hotel: Hotel, night: date, room_type: RoomType) -> dict:
        room_type = RoomType(room_type)
        capacity = 12 + stable_int(self.seed, hotel.id, room_type, "capacity") % 29
        # Occupancy is simulated demand, not a real hotel's reported occupancy.
        demand = 65 if night.month in {11, 12, 1, 2, 3} else 40
        demand += stable_int(self.seed, hotel.id, room_type, night, "demand") % 26
        sold = capacity * demand // 100
        return {"capacity": capacity, "baseline_sold": sold}

    def _purge(self, now: datetime):
        while self._expires and self._expires[0][0] <= now:
            _, key = heapq.heappop(self._expires)
            h = self._holds.pop(key)
            group = (h["hotel_id"], h["room_type"])
            self._by_room[group].discard(key)
            if not self._by_room[group]:
                del self._by_room[group]
            for counts, value in (
                (self._by_client, h["client_id"]),
                (self._by_hotel, h["hotel_id"]),
            ):
                counts[value] -= 1
                if not counts[value]:
                    del counts[value]

    def throttle(self, client_id="local"):
        """60 attempts/minute per transport client, before token/body processing."""
        with self._lock:
            now = self.clock()
            cutoff = now - timedelta(minutes=1)
            attempts = self._attempts.get(client_id)
            if attempts is None:
                self._attempts = {k: v for k, v in self._attempts.items() if v[-1] > cutoff}
                if len(self._attempts) >= 10_000:
                    raise HoldLimit("hold_capacity_reached", 503)
                attempts = self._attempts.setdefault(client_id, deque())
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            if len(attempts) >= 60:
                raise HoldLimit()
            attempts.append(now)

    def _night(self, hotel: Hotel, night: date, room_type: RoomType) -> dict:
        stock = self.stock(hotel, night, room_type)
        held = sum(
            1
            for key in self._by_room.get((hotel.id, room_type), ())
            if (h := self._holds[key])["checkin"]
            <= night
            < h["checkin"] + timedelta(days=h["nights"])
        )
        remaining = stock["capacity"] - stock["baseline_sold"] - held
        if remaining < 0:
            raise RuntimeError("inventory invariant violated")
        return {"date": night, **stock, "held": held, "available": remaining}

    def availability(
        self,
        hotel: Hotel,
        checkin: date,
        nights: int,
        room_type: RoomType = RoomType.STANDARD,
    ) -> dict:
        if not isinstance(checkin, date) or type(nights) is not int or not 1 <= nights <= 30:
            raise ValueError("nights must be 1–30 and checkin must be a date")
        room_type = RoomType(room_type)
        with self._lock:
            self._purge(self.clock())
            nightly = [
                self._night(hotel, checkin + timedelta(days=i), room_type) for i in range(nights)
            ]
            return {
                "hotel_id": hotel.id,
                "room_type": room_type,
                "nights": nightly,
                "available": min(n["available"] for n in nightly),
            }

    def hold(self, hotel: Hotel, quote: dict, *, confirm: bool, client_id="local") -> dict:
        if confirm is not True:
            raise ValueError("confirm=true is required for a mock hold")
        with self._lock:
            now = self.clock()
            self._purge(now)
            if self._by_client[client_id] >= 32:
                raise HoldLimit("hold_client_capacity_reached")
            if self._by_hotel[hotel.id] >= 256:
                raise HoldLimit("hold_hotel_capacity_reached", 503)
            if len(self._holds) >= 10_000:
                raise HoldLimit("hold_capacity_reached", 503)
            checkin = date.fromisoformat(quote["checkin"])
            room_type = RoomType(quote["room_type"])
            if hotel.id != quote["hotel_id"]:
                raise ValueError("quote hotel does not match hold hotel")
            available = self.availability(hotel, checkin, quote["nights"], room_type)
            if available["available"] < 1:
                raise SoldOut("no mock inventory for the complete stay")
            hold_id = "mock_" + uuid4().hex
            hold = {
                "hold_id": hold_id,
                "hotel_id": hotel.id,
                "client_id": client_id,
                "room_type": room_type,
                "checkin": checkin,
                "nights": quote["nights"],
                "rate_id": quote["rate_id"],
                "computed_at": quote["computed_at"],
                "created_at": now,
                "expires_at": now + timedelta(minutes=15),
                "mock_only": True,
                "booked": False,
                "quote": quote,
            }
            self._holds[hold_id] = hold
            self._by_room[(hotel.id, room_type)].add(hold_id)
            self._by_client[client_id] += 1
            self._by_hotel[hotel.id] += 1
            heapq.heappush(self._expires, (hold["expires_at"], hold_id))
            return dict(hold)
