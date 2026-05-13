import argparse
import json
import sys
import urllib.error
import urllib.request


BASE_URL = "http://127.0.0.1:8000"


def http_get(path: str):
    req = urllib.request.Request(BASE_URL + path, method="GET")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post(path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_health(_args):
    print_json(http_get("/api/health"))


def cmd_dashboard(_args):
    print_json(http_get("/api/dashboard"))


def cmd_planner(_args):
    print_json(http_get("/api/spot-planner"))


def cmd_runtime(_args):
    print_json(http_get("/api/debug/runtime"))


def cmd_risk_status(_args):
    print_json(http_get("/api/debug/risk/status"))


def cmd_risk_reset(_args):
    print_json(http_post("/api/debug/risk/reset", {}))


def cmd_logs_tail(args):
    print_json(http_get(f"/api/debug/logs/tail?lines={args.lines}"))


def cmd_open_fut(args):
    payload = {
        "symbol": args.symbol,
        "side": args.side,
        "price": args.price,
        "atr": args.atr,
        "margin_usdt": args.margin,
        "leverage": args.leverage,
        "tp_mult": args.tp_mult,
        "sl_mult": args.sl_mult,
        "setup_type": args.setup_type,
        "args_text": args.args_text,
    }
    print_json(http_post("/api/debug/open-futures", payload))


def cmd_close_fut(args):
    payload = {
        "price": args.price,
        "reason": args.reason,
    }
    print_json(http_post("/api/debug/close-futures", payload))


def cmd_open_spot(args):
    payload = {
        "symbol": args.symbol,
        "price": args.price,
        "atr": args.atr,
        "order_usdt": args.usdt,
        "tp_mult": args.tp_mult,
        "setup_type": args.setup_type,
        "args_text": args.args_text,
    }
    print_json(http_post("/api/debug/open-spot", payload))


def cmd_close_spot(args):
    payload = {
        "symbol": args.symbol,
        "price": args.price,
        "reason": args.reason,
    }
    print_json(http_post("/api/debug/close-spot", payload))


def cmd_close_all_spot(args):
    prices = {}
    for item in args.price:
        symbol, raw_price = item.split("=", 1)
        prices[symbol] = float(raw_price)

    payload = {
        "prices": prices,
        "reason": args.reason,
    }
    print_json(http_post("/api/debug/close-all-spot", payload))


def build_parser():
    parser = argparse.ArgumentParser(description="VORTEX console debug client")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("health")
    p.set_defaults(func=cmd_health)

    p = sub.add_parser("dashboard")
    p.set_defaults(func=cmd_dashboard)

    p = sub.add_parser("planner")
    p.set_defaults(func=cmd_planner)

    p = sub.add_parser("runtime")
    p.set_defaults(func=cmd_runtime)

    p = sub.add_parser("risk-status")
    p.set_defaults(func=cmd_risk_status)

    p = sub.add_parser("risk-reset")
    p.set_defaults(func=cmd_risk_reset)

    p = sub.add_parser("tail-log")
    p.add_argument("--lines", type=int, default=50)
    p.set_defaults(func=cmd_logs_tail)

    p = sub.add_parser("open-fut")
    p.add_argument("symbol")
    p.add_argument("side", choices=["LONG", "SHORT"])
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--atr", type=float, required=True)
    p.add_argument("--margin", type=float, default=20.0)
    p.add_argument("--leverage", type=float, default=3.0)
    p.add_argument("--tp-mult", type=float, default=2.5)
    p.add_argument("--sl-mult", type=float, default=1.3)
    p.add_argument("--setup-type", default="manual_fut")
    p.add_argument("--args-text", default="manual futures open")
    p.set_defaults(func=cmd_open_fut)

    p = sub.add_parser("close-fut")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--reason", default="MANUAL")
    p.set_defaults(func=cmd_close_fut)

    p = sub.add_parser("open-spot")
    p.add_argument("symbol")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--atr", type=float, required=True)
    p.add_argument("--usdt", type=float, default=20.0)
    p.add_argument("--tp-mult", type=float, default=3.0)
    p.add_argument("--setup-type", default="manual_spot")
    p.add_argument("--args-text", default="manual spot open")
    p.set_defaults(func=cmd_open_spot)

    p = sub.add_parser("close-spot")
    p.add_argument("symbol")
    p.add_argument("--price", type=float, required=True)
    p.add_argument("--reason", default="MANUAL")
    p.set_defaults(func=cmd_close_spot)

    p = sub.add_parser("close-all-spot")
    p.add_argument("--price", nargs="+", required=True, help="format BTCUSDT=68000 ETHUSDT=3200")
    p.add_argument("--reason", default="MANUAL")
    p.set_defaults(func=cmd_close_all_spot)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        args.func(args)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        print(f"HTTPError {exc.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as exc:
        print(f"Connection error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()