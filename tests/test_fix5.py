from fastapi.testclient import TestClient

from rate_truth.geo import distance
from rate_truth.hotel_groups import hotel_groups
from rate_truth.mcp_server.service import Gateway
from rate_truth.web.app import create_app


def test_hotel_order_groups_filters_and_details(engine, hotel):
    def h(identifier, name, stars=None, **kwargs):
        return hotel.model_copy(update={"id": f"node/{identifier}", "name": name,
                                        "stars": stars, **kwargs})

    hotels = [
        h(1, "العربية"),
        h(2, "Zulu", 5),
        h(3, "Alpha", 5),
        h(4, "Four", 4),
        h(5, "العربية إنجليزي", name_en="Bravo"),
        h(6, "My hotel dorus"),
        h(7, " my HOTEL dorus ", lon=hotel.lon + 0.0001),
        h(8, "My hotel dorus", lon=hotel.lon + 0.0002),
        h(9, "My hotel dorus", lon=hotel.lon + 0.0003),
        h(10, "My hotel dorus", lon=hotel.lon + 0.01),
        h(11, "Different name", lon=hotel.lon + 0.0001),
    ]
    engine.catalog._hotels = {h.id: h for h in hotels}
    gateway = Gateway(engine)
    result = gateway.search(limit=100, display=True)
    items = result["items"]
    assert [h["id"] for h in items[:5]] == ["node/3", "node/2", "node/4", "node/5", "node/11"]
    assert items[-1]["id"] == "node/1"
    assert result["total"] == len(hotels) - 3
    group = next(h for h in items if h["id"] == "node/6")
    assert set(group["mapped_osm_ids"]) == {f"node/{n}" for n in range(6, 10)}
    assert gateway.search(q="Bravo", display=True)["items"][0]["name_en"] == "Bravo"
    assert gateway.search(stars=5, display=True)["total"] == 2
    assert gateway.search(limit=1, offset=1, display=True)["items"][0]["id"] == "node/2"
    assert gateway.search(max_total=0, display=True)["total"] == 0
    assert gateway.search(limit=100)["total"] == len(hotels)  # MCP identities stay distinct.
    with TestClient(create_app(engine, force_replay=True)) as client:
        detail = client.get("/api/hotels/node/7").json()
    assert detail["hotel"]["id"] == "node/7"
    assert detail["hotel"]["mapped_osm_ids"] == group["mapped_osm_ids"]
    assert len(detail["card"]["facts"]) > 8  # Full resource is preserved.


def test_duplicate_group_does_not_chain_or_merge_aliases(hotel):
    hotels = [hotel.model_copy(update={"id": f"node/{i + 1}", "name": "Same",
                                      "lon": hotel.lon + i * 0.001}) for i in range(3)]
    assert distance(hotels[0].model_dump(), hotels[-1].model_dump()) > 150
    groups = hotel_groups(hotels)
    assert groups["node/1"] == groups["node/2"] == ["node/1", "node/2"]
    assert groups["node/3"] == ["node/3"]
    aliases = [h.model_copy(update={"name": f"Different {i}", "name_en": "Same"})
               for i, h in enumerate(hotels)]
    assert all(len(ids) == 1 for ids in hotel_groups(aliases).values())


def test_fault_sources_are_structured_and_descriptions_compact(engine):
    with TestClient(create_app(engine, force_replay=True)) as client:
        faults = client.get("/api/faults").json()
    assert len(faults) == 7
    assert all(len(f["description"]) < 100 and "https://" not in f["description"] for f in faults)
    assert all(isinstance(f["sources"], list) for f in faults)
    assert [s["label"] for s in faults[-1]["sources"]] == [
        "The National, 21 May 2026", "Resolution 40/2026 (official, Arabic)",
    ]
