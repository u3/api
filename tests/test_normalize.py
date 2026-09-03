from u3ingest.canonical.markets import canon_market_from_name, canon_market_oddspapi, canon_selection
from u3ingest.mapping.registry import BookRegistry, FixtureRegistry
from u3ingest.providers.oddspapi.normalize import MarketDict, OddsPapiNormalizer
from u3ingest.providers.opticodds.normalize import OpticOddsNormalizer
from u3ingest.providers.sharpsports.normalize import SharpSportsNormalizer

OO_FX = {"id": "2026090552B5D9A7", "game_id": "42573-28098-2026-09-04", "start_date": "2026-09-05T14:00:00Z", "status": "unplayed",
         "home_competitors": [{"id": "77CBFB371ED9", "name": "Ipswich Town FC"}], "away_competitors": [{"id": "A1", "name": "Liverpool FC"}],
         "home_team_display": "Ipswich Town FC", "away_team_display": "Liverpool FC", "sport": {"id": "soccer"}, "league": {"id": "england_-_premier_league"},
         "home_rotation_number": 101, "away_rotation_number": 102,
         "odds": [{"id": "42573-28098-2026-09-04:pinnacle:moneyline:liverpool_fc", "sportsbook": "Pinnacle", "market": "Moneyline", "market_id": "moneyline",
                   "name": "Liverpool FC", "price": -190, "points": None, "selection": "Liverpool FC", "normalized_selection": "liverpool_fc", "selection_line": None,
                   "timestamp": 1788423451.03, "grouping_key": "default", "is_main": True, "player_id": None, "team_id": "A1", "limits": {"max": 2000}, "order_book": None},
                  {"id": "x:kalshi:total_goals:over_3_5", "sportsbook": "Kalshi", "market": "Total Goals", "market_id": "total_goals", "name": "Over 3.5", "price": 120,
                   "points": 3.5, "selection": "Over 3.5", "selection_line": "over", "timestamp": 1788423452.0, "is_main": True, "player_id": None, "team_id": None,
                   "limits": None, "order_book": [[2.2, 150.0], [2.25, 300.0]], "source_ids": {"market_id": "KXEPL-XYZ"}},
                  {"id": "x:draftkings:1st_half_player_shots:salah_over_1_5", "sportsbook": "DraftKings", "market": "1st Half Player Shots", "market_id": "1st_half_player_shots",
                   "name": "Mohamed Salah Over 1.5", "price": -110, "points": 1.5, "selection": "Mohamed Salah", "selection_line": "over", "timestamp": 1788423453.0,
                   "is_main": True, "player_id": "P9", "team_id": "A1", "limits": None, "order_book": None}]}

OP_FX = {"fixtureId": "id1000001772221244", "startTime": 1788969600, "sport": {"sportId": 10}, "tournament": {"tournamentId": 17},
         "participants": {"participant1Name": "Ipswich Town", "participant2Name": "Liverpool", "participant1RotNr": None},
         "externalProviders": {"opticoddsId": "2026090552B5D9A7", "betradarId": 1772221244, "pinnacleId": 55}, "status": {"statusName": "Pre-Game"}}
OP_MARKETS = [{"marketId": 10100, "sportId": 10, "playerProp": False, "handicap": 0.0, "period": "result", "marketType": "1x2", "marketName": "1X2",
               "outcomes": [{"outcomeId": 10100, "outcomeName": "1"}, {"outcomeId": 10101, "outcomeName": "2"}, {"outcomeId": 10102, "outcomeName": "X"}]},
              {"marketId": 14200, "sportId": 10, "playerProp": False, "handicap": -1.5, "period": "result", "marketType": "spreads", "marketName": "Handicap",
               "outcomes": [{"outcomeId": 14200, "outcomeName": "1"}, {"outcomeId": 14201, "outcomeName": "2"}]}]
OP_ODDS = {"fixtureId": "id1000001772221244", "bookmakers": {"kalshi": {"participantsRotated": True}},
           "odds": {"draftkings": {"id1000001772221244:draftkings:10101:0": {"outcomeId": 10101, "playerId": 0, "price": 1.5, "priceAmerican": -200, "active": True,
                                                                             "changedAt": 1788352774674, "bookmakerChangedAt": 1788352774597, "marketId": 10100, "mainLine": False}},
                    "kalshi": {"id1000001772221244:kalshi:14200:0": {"outcomeId": 14200, "playerId": 0, "price": 2.128, "active": True, "changedAt": 1788431742144,
                                                                     "bookmakerChangedAt": 1788431742052, "limit": 48.41, "marketId": 14200, "mainLine": False,
                                                                     "meta": {"back": [{"price": 2.128, "size": 103.0}], "lay": [{"price": 1.724, "size": 2.0}]}}}}}
SS_EVENT = {"id": "EVNT_1", "oddsjamId": "42573-28098-2026-09-04", "startTime": "2026-09-05T14:00:00Z", "contestantHome": {"id": "TEAM_H", "fullName": "Ipswich Town FC"},
            "contestantAway": {"id": "TEAM_A", "fullName": "Liverpool FC"}, "sport": "soccer", "league": "EPL"}
SS_PRICES = {"eventId": "EVNT_1", "markets": [{"id": "MKT_1", "name": "1st Half Spread", "marketOffers": [{"id": "MKTO_1", "player": None, "team": None, "marketSelections": [
    {"id": "MRKT_1", "position": "Ipswich Town FC", "positionId": "TEAM_H", "books": [{"id": "BOOK_1", "abbr": "br", "name": "BetRivers",
                                                                                      "prices": [{"line": 1.0, "odds": -360, "main": False, "live": False}, {"line": 0.5, "odds": -150, "main": True, "live": False}]}]}]}]},
    {"id": "MKT_2", "name": "Player Prop Total Shots", "marketOffers": [{"id": "MKTO_2", "player": {"id": "PLYR_9"}, "team": None, "marketSelections": [
        {"id": "MRKT_2", "position": "Over", "positionId": None, "books": [{"id": "BOOK_2", "abbr": "dk", "name": "DraftKings", "prices": [{"line": 2.5, "odds": -115, "main": True, "live": False}]}]}]}]}]}


def test_market_keys():
    assert canon_market_from_name("Moneyline") == ("moneyline", "full")
    assert canon_market_from_name("1st Half Moneyline") == ("moneyline", "1h")
    assert canon_market_from_name("Point Spread") == ("spread", "full") and canon_market_from_name("Run Line") == ("spread", "full")
    assert canon_market_from_name("Total Points")[0] == "total" and canon_market_from_name("Team Total") == ("team_total", "full")
    assert canon_market_from_name("Player Prop Total Passing Yards") == ("player:passing_yards", "full")
    assert canon_market_from_name("1st Quarter Player Points") == ("player:points", "1q")
    assert canon_market_oddspapi("1x2", "result") == ("3way", "full") and canon_market_oddspapi("playertotals-assists", "result") == ("player:assists", "full")
    assert canon_selection("X", home="A", away="B") == "draw" and canon_selection("Liverpool FC -1.5", home="Ipswich", away="Liverpool FC") == "away"


def test_registry_joins_all_three_providers():
    fr = FixtureRegistry()
    fr.add_opticodds(OO_FX)
    op = fr.add_oddspapi(OP_FX)
    ss = fr.add_sharpsports(SS_EVENT, "england_-_premier_league")
    assert op.fixture_id == ss.fixture_id == "2026090552B5D9A7"
    assert fr.canonical_for("oddspapi", "id1000001772221244") == "2026090552B5D9A7" and fr.canonical_for("sharpsports", "EVNT_1") == "2026090552B5D9A7"
    assert op.betradar_id == "1772221244" and ss.sharpsports_id == "EVNT_1"
    # team+time fallback when oddsjamId is missing
    ss2 = fr.add_sharpsports({**SS_EVENT, "id": "EVNT_2", "oddsjamId": None, "startTime": "2026-09-05T14:05:00Z"}, "epl")
    assert ss2.fixture_id == "2026090552B5D9A7"


def test_opticodds_normalizer():
    books, fr = BookRegistry(), FixtureRegistry()
    n = OpticOddsNormalizer(books, fr)
    qs, obs = n.quotes_from_fixture_rows([OO_FX], recv_ns=10)
    ml, tot, prop = qs
    assert (ml.book_id, ml.market, ml.selection, ml.price_us, ml.price_dec, ml.limit_max, ml.source_ts_ms) == ("pinnacle", "moneyline", "away", -190, 1.526316, 2000, 1788423451030)
    assert (tot.book_id, tot.market, tot.selection, tot.line) == ("kalshi", "total", "over", 3.5) and len(obs) == 2 and obs[0].venue_market_id == "KXEPL-XYZ"
    assert (prop.market, prop.period, prop.selection, prop.line) == ("player:shots", "1h", "player:P9:over", 1.5)
    lq, _ = n.quotes_from_sse("locked-odds", {"data": [OO_FX["odds"][0]]}, recv_ns=11)
    assert lq[0].event_kind == "lock" and lq[0].active is False and lq[0].fixture_id == "2026090552B5D9A7"


def test_oddspapi_normalizer_rotation_and_depth():
    books, fr = BookRegistry(), FixtureRegistry()
    fr.add_opticodds(OO_FX)
    fr.add_oddspapi(OP_FX)
    n = OddsPapiNormalizer(books, fr, MarketDict(OP_MARKETS))
    qs, obs = n.quotes(OP_ODDS, recv_ns=5, gateway_ts_ms=1788431742379)
    dk = next(q for q in qs if q.book_id == "draftkings")
    assert (dk.fixture_id, dk.market, dk.selection, dk.price_us, dk.source_ts_ms, dk.gateway_ts_ms) == ("2026090552B5D9A7", "3way", "away", -200, 1788352774597, 1788431742379)
    ks = next(q for q in qs if q.book_id == "kalshi")
    assert ks.market == "spread" and ks.selection == "away" and ks.line == 1.5 and ks.limit_max == 48.41  # rotated book: participant1 -> away, sign flipped
    assert [(o.side, o.price, o.size) for o in obs] == [("back", 2.128, 103.0), ("lay", 1.724, 2.0)]


def test_sharpsports_normalizer():
    books, fr = BookRegistry(), FixtureRegistry()
    fr.add_opticodds(OO_FX)
    n = SharpSportsNormalizer(books, fr)
    n.remember_event(SS_EVENT, "england_-_premier_league")
    qs = n.quotes(SS_PRICES, recv_ns=7)
    assert len(qs) == 3 and all(q.fixture_id == "2026090552B5D9A7" for q in qs)
    assert (qs[0].book_id, qs[0].market, qs[0].period, qs[0].selection, qs[0].line, qs[0].price_us, qs[0].is_main) == ("betrivers", "spread", "1h", "home", 1.0, -360, False)
    assert (qs[2].book_id, qs[2].market, qs[2].selection, qs[2].line) == ("draftkings", "player:shots", "player:PLYR_9:over", 2.5)
