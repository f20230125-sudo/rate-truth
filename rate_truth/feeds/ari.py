"""Per-date ARI for one-night products; LOS discounts are sent via Pull, not approximated."""

from uuid import uuid4

from lxml import etree

from rate_truth.contract import folio
from rate_truth.feeds.common import OTA, Feed, element, timestamp
from rate_truth.geo import UNKNOWN_STARS


def build(engine, stay):
    hotel = engine.catalog.get(stay.hotel_id)
    folios = []

    def root(name):
        r = etree.Element(
            f"{{{OTA}}}{name}",
            nsmap={None: OTA},
            EchoToken=uuid4().hex,
            TimeStamp=timestamp(),
            Version="3.0",
        )
        r.append(etree.Comment("SYNTHETIC; per-date one-night prices; LOS discounts use Pull"))
        if hotel.stars is None:
            r.append(etree.Comment(UNKNOWN_STARS))
        return r

    rate = root("OTA_HotelRateAmountNotifRQ")
    rate.set("NotifType", "Overlay")
    avail = root("OTA_HotelAvailNotifRQ")
    inv = root("OTA_HotelInvCountNotifRQ")
    rates = element(rate, f"{{{OTA}}}RateAmountMessages", HotelCode=hotel.id)
    avails = element(avail, f"{{{OTA}}}AvailStatusMessages", HotelCode=hotel.id)
    inventories = element(inv, f"{{{OTA}}}Inventories", HotelCode=hotel.id)
    for q in engine.quote_nights(stay):
        from datetime import date

        day = date.fromisoformat(q["checkin"])
        f = folio(q, hotel)
        folios.append(f)
        stock = engine.inventory.availability(hotel, day, 1, stay.room_type)["available"]

        def control(parent, with_plan=True, day=day):
            return element(
                parent,
                f"{{{OTA}}}StatusApplicationControl",
                Start=day.isoformat(),
                End=day.isoformat(),
                InvTypeCode=stay.room_type.value,
                **({"RatePlanCode": stay.plan.value} if with_plan else {}),
            )

        message = element(rates, f"{{{OTA}}}RateAmountMessage")
        control(message)
        message.append(etree.Comment(f"rate_id={f['rate_id']} computed_at={f['computed_at']}"))
        if hotel.stars is None:
            message.append(etree.Comment(UNKNOWN_STARS))
        amounts = element(
            element(element(message, f"{{{OTA}}}Rates"), f"{{{OTA}}}Rate"),
            f"{{{OTA}}}BaseByGuestAmts",
        )
        element(
            amounts,
            f"{{{OTA}}}BaseByGuestAmt",
            AmountBeforeTax=q["base"],
            AmountAfterTax=f["total"],
            CurrencyCode="AED",
            NumberOfGuests=stay.guests,
        )
        message = element(avails, f"{{{OTA}}}AvailStatusMessage")
        control(message)
        element(
            message,
            f"{{{OTA}}}RestrictionStatus",
            Status="Open" if stock else "Close",
            Restriction="Master",
        )
        inventory = element(inventories, f"{{{OTA}}}Inventory")
        control(inventory, with_plan=False)
        element(
            element(inventory, f"{{{OTA}}}InvCounts"),
            f"{{{OTA}}}InvCount",
            Count=stock,
            CountType="2",
        )
    return [
        Feed.create(kind, r, folios if kind == "ari_rate" else [])
        for kind, r in (("ari_rate", rate), ("ari_avail", avail), ("ari_inv", inv))
    ]
