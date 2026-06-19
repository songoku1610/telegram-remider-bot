import argparse
import json

from weather import GoogleWeatherUnsupportedLocation, format_weather_info, get_weather_info
from weatherAPI import get_tomorrow_day_forecast


def main():
    parser = argparse.ArgumentParser(description="Test Google Weather API integration.")
    parser.add_argument(
        "--city",
        help="City to check. If omitted, WEATHER_CITY from .env is used.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print full traceback when the test fails.",
    )
    args = parser.parse_args()

    try:
        weather = get_weather_info(args.city)
        print("Raw weather data:")
        print(json.dumps(weather, ensure_ascii=False, indent=2))
        print()
        print("Formatted message:")
        print(format_weather_info(args.city))
    except GoogleWeatherUnsupportedLocation as exc:
        print(f"Weather test failed: {exc}")
        print(
            "Google Weather API coverage currently does not include current "
            "conditions for Vietnam. Test with a supported city, for example:"
        )
        print('python run_test.py --city "Singapore"')
        if args.debug:
            raise
    except Exception as exc:
        print(f"Weather test failed: {exc}")
        if args.debug:
            raise

    print()
    print("=== Tomorrow day forecast (get_tomorrow_day_forecast) ===")
    try:
        forecast = get_tomorrow_day_forecast(args.city)
        print("Raw forecast data:")
        print(json.dumps(forecast, ensure_ascii=False, indent=2))
        print()
        location = forecast["location"]
        if forecast.get("country"):
            location = f"{location}, {forecast['country']}"
        print(
            f"Dự báo ngày mai tại {location}: "
            f"TB {forecast['temperature_c']} C "
            f"(cao {forecast['max_temp_c']} C / thấp {forecast['min_temp_c']} C), "
            f"độ ẩm {forecast['humidity']}%, "
            f"khả năng mưa {forecast['chance_of_rain']}%, "
            f"gió tối đa {forecast['wind_kph']} km/h, "
            f"{forecast['condition']}."
        )
    except Exception as exc:
        print(f"Tomorrow day forecast test failed: {exc}")
        if args.debug:
            raise


if __name__ == "__main__":
    main()
