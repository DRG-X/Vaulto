"""
Recorded provider response shapes.

These mirror the payload structures the three provider modules parse. They let
the parsers, the fee-model re-basing and the ranking be exercised end to end
without reaching the live APIs.

IMPORTANT: these are hand-built to the documented response SHAPE, not captured
from a live call — this environment's egress policy blocks wise.com,
api.remitly.io and westernunion.com. They pin our parsing logic and the maths
built on top of it. They do NOT prove the field names still match production;
re-record them against live responses before trusting a deploy.
"""

WISE_COMPARISONS = {
    "sourceCurrency": "USD",
    "targetCurrency": "INR",
    "sourceAmount": 1000,
    "midMarketRate": 83.4210,
    "providers": [
        {
            "id": 1,
            "alias": "wise",
            "name": "Wise",
            "quotes": [
                {
                    # Deliberately NOT first-by-preference, to prove the old
                    # `quotes[0]` behaviour is gone: this card-funded row would
                    # have been picked blindly.
                    "rate": 83.4210,
                    "fee": 12.85,
                    "receivedAmount": 82393.10,
                    "sourcePaymentMethod": "DEBIT_CARD",
                    "targetPaymentMethod": "BANK_TRANSFER",
                    "deliveryEstimation": {"duration": {"min": "PT0S", "max": "PT30M"}},
                },
                {
                    "rate": 83.4210,
                    "fee": 5.46,
                    "receivedAmount": 82965.87,
                    "sourcePaymentMethod": "BANK_TRANSFER",
                    "targetPaymentMethod": "BANK_TRANSFER",
                    "deliveryEstimation": {"duration": {"min": "PT1H", "max": "PT20H"}},
                },
            ],
        },
        {"alias": "someotherbank", "name": "Other", "quotes": [{"rate": 80.1, "fee": 25.0}]},
    ],
}

# Remitly publishes its numbers as decimal STRINGS. Running them through
# float() — as the old code did — discarded the exact values before any
# arithmetic happened.
REMITLY_ESTIMATE = {
    "estimate": {
        "pay_in_method": "BANK",
        "pay_out_method": "BANK_DEPOSIT",
        "receive_amount": "83050.00",
        "fee": {"total_fee_amount": "3.99"},
        "exchange_rate": {
            "base_rate": "83.05",
            "promotional_exchange_rate": "84.20",
        },
    },
    "pay_out_price_estimates": {
        "estimates": [
            {
                "pay_in_method": "DEBIT",
                "pay_out_method": "CASH_PICKUP",
                "receive_amount": "82800.00",
                "fee": {"total_fee_amount": "6.99"},
                "exchange_rate": {"base_rate": "82.80", "promotional_exchange_rate": "82.80"},
            },
        ]
    },
}

WESTERN_UNION_CATALOG = {
    "response_status": {"code": "P0000", "message": "OK"},
    "services_groups": [
        {
            "service_name": "Bank Deposit",
            "pay_groups": [
                {
                    "fund_in": "BANK",
                    "pay_out": "BANK_DEPOSIT",
                    "fx_rate": 82.55,
                    "gross_fee": 0.0,
                    "receive_amount": 82550.00,
                    "speed_indicator": "2-3",
                },
                {
                    "fund_in": "DEBIT",
                    "pay_out": "BANK_DEPOSIT",
                    "fx_rate": 82.40,
                    "gross_fee": 2.99,
                    "receive_amount": 82400.00,
                    "speed_indicator": "0",
                },
            ],
        },
        {
            "service_name": "Cash Pickup",
            "pay_groups": [
                {
                    # The highest raw receive amount in the catalog — which is
                    # exactly why "pick the biggest number" was the wrong rule.
                    "fund_in": "DEBIT",
                    "pay_out": "CASH_PICKUP",
                    "fx_rate": 83.10,
                    "gross_fee": 4.99,
                    "receive_amount": 83100.00,
                    "speed_indicator": "0",
                },
            ],
        },
    ],
}

WU_UNSUPPORTED_CORRIDOR = {
    "response_status": {"code": "P1008", "message": "Corridor not supported"},
}
