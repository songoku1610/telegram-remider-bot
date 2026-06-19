import json
import os
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv


load_dotenv()

WEATHER_API_CURRENT_URL = "https://api.weatherapi.com/v1/current.json"
WEATHER_API_FORECAST_URL = "https://api.weatherapi.com/v1/forecast.json"
TOMORROW_FORECAST_HOUR = "07:00"


def _load_weatherapi_config():
    api_key = os.getenv("WEATHER_API_KEY")
    city = os.getenv("WEATHER_CITY")

    if not api_key:
        raise ValueError("Missing WEATHER_API_KEY in .env")
    if not city:
        raise ValueError("Missing WEATHER_CITY in .env")

    return api_key, city


def _get_json(url):
    try:
        with urlopen(url, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
            data = json.loads(detail)
            message = data.get("error", {}).get("message") or detail
        except Exception:
            message = str(exc.reason)
        raise RuntimeError(f"WeatherAPI.com request failed: HTTP {exc.code} - {message}") from exc
    except URLError as exc:
        raise RuntimeError(f"WeatherAPI.com request failed: {exc.reason}") from exc


def classify_weather(condition_text, cloud, precip_mm, is_day):
    text = (condition_text or "").lower()

    if precip_mm > 0 or any(
        word in text
        for word in ["rain", "drizzle", "storm", "thunder", "shower", "mua", "mưa"]
    ):
        return "mua"
    if cloud >= 70 or any(
        word in text
        for word in ["overcast", "cloudy", "u am", "u ám", "nhieu may", "nhiều mây"]
    ):
        return "nhieu may"
    if cloud >= 30 or any(
        word in text
        for word in ["partly cloudy", "it may", "ít mây", "co may", "có mây"]
    ):
        return "it may"
    if any(word in text for word in ["sun", "clear", "fair", "nang", "nắng", "quang"]):
        return "nang" if is_day else "troi quang"

    return "nang" if is_day else "troi quang"


def get_weather_info(city=None):
    api_key, default_city = _load_weatherapi_config()
    location_query = city or default_city
    query = urlencode(
        {
            "key": api_key,
            "q": location_query,
            "aqi": "no",
            "lang": "vi",
        }
    )
    data = _get_json(f"{WEATHER_API_CURRENT_URL}?{query}")

    location = data.get("location", {})
    current = data.get("current", {})
    condition = current.get("condition", {})
    condition_text = condition.get("text", "")
    cloud = current.get("cloud", 0) or 0
    precip_mm = current.get("precip_mm", 0) or 0
    is_day = current.get("is_day", 1) == 1

    return {
        "location": location.get("name", location_query),
        "region": location.get("region"),
        "country": location.get("country"),
        "local_time": location.get("localtime"),
        "temperature_c": current.get("temp_c"),
        "feels_like_c": current.get("feelslike_c"),
        "humidity": current.get("humidity"),
        "wind_kph": current.get("wind_kph"),
        "wind_dir": current.get("wind_dir"),
        "condition": condition_text,
        "condition_icon": condition.get("icon"),
        "cloud": cloud,
        "precip_mm": precip_mm,
        "summary": classify_weather(condition_text, cloud, precip_mm, is_day),
    }


def get_tomorrow_7am_forecast(city=None):
    api_key, default_city = _load_weatherapi_config()
    location_query = city or default_city
    tomorrow = date.today() + timedelta(days=1)
    query = urlencode(
        {
            "key": api_key,
            "q": location_query,
            "dt": tomorrow.isoformat(),
            "aqi": "no",
            "alerts": "no",
            "lang": "vi",
        }
    )
    data = _get_json(f"{WEATHER_API_FORECAST_URL}?{query}")

    location = data.get("location", {})
    forecast_days = data.get("forecast", {}).get("forecastday", [])
    if not forecast_days:
        raise RuntimeError(f"No forecast data for {location_query} on {tomorrow.isoformat()}")

    hours = forecast_days[0].get("hour", [])
    forecast_hour = next(
        (hour for hour in hours if hour.get("time", "").endswith(f" {TOMORROW_FORECAST_HOUR}")),
        None,
    )
    if not forecast_hour:
        raise RuntimeError(f"No forecast data for {location_query} at {TOMORROW_FORECAST_HOUR}")

    condition = forecast_hour.get("condition", {})
    condition_text = condition.get("text", "")
    cloud = forecast_hour.get("cloud", 0) or 0
    precip_mm = forecast_hour.get("precip_mm", 0) or 0
    is_day = forecast_hour.get("is_day", 1) == 1

    return {
        "location": location.get("name", location_query),
        "region": location.get("region"),
        "country": location.get("country"),
        "forecast_time": forecast_hour.get("time"),
        "temperature_c": forecast_hour.get("temp_c"),
        "feels_like_c": forecast_hour.get("feelslike_c"),
        "humidity": forecast_hour.get("humidity"),
        "chance_of_rain": forecast_hour.get("chance_of_rain"),
        "wind_kph": forecast_hour.get("wind_kph"),
        "wind_dir": forecast_hour.get("wind_dir"),
        "condition": condition_text,
        "condition_icon": condition.get("icon"),
        "cloud": cloud,
        "precip_mm": precip_mm,
        "summary": classify_weather(condition_text, cloud, precip_mm, is_day),
    }


def get_tomorrow_day_forecast(city=None):
    api_key, default_city = _load_weatherapi_config()
    location_query = city or default_city
    tomorrow = date.today() + timedelta(days=1)
    query = urlencode(
        {
            "key": api_key,
            "q": location_query,
            "dt": tomorrow.isoformat(),
            "aqi": "no",
            "alerts": "no",
            "lang": "vi",
        }
    )
    data = _get_json(f"{WEATHER_API_FORECAST_URL}?{query}")

    location = data.get("location", {})
    forecast_days = data.get("forecast", {}).get("forecastday", [])
    if not forecast_days:
        raise RuntimeError(f"No forecast data for {location_query} on {tomorrow.isoformat()}")

    day = forecast_days[0].get("day", {})
    condition = day.get("condition", {})
    condition_text = condition.get("text", "")
    precip_mm = day.get("totalprecip_mm", 0) or 0

    return {
        "location": location.get("name", location_query),
        "region": location.get("region"),
        "country": location.get("country"),
        "forecast_date": tomorrow.isoformat(),
        "temperature_c": day.get("avgtemp_c"),
        "max_temp_c": day.get("maxtemp_c"),
        "min_temp_c": day.get("mintemp_c"),
        "feels_like_c": None,
        "humidity": day.get("avghumidity"),
        "chance_of_rain": day.get("daily_chance_of_rain"),
        "wind_kph": day.get("maxwind_kph"),
        "wind_dir": None,
        "condition": condition_text,
        "condition_icon": condition.get("icon"),
        "cloud": None,
        "precip_mm": precip_mm,
        "summary": classify_weather(condition_text, 0, precip_mm, True),
    }


def weather_icon(summary):
    return {
        "nang": "☀️",
        "troi quang": "☀️",
        "mua": "🌧️",
        "it may": "⛅",
        "nhieu may": "☁️",
    }.get(summary, "")


def weather_summary_text(summary):
    return {
        "nang": "nắng",
        "troi quang": "trời quang",
        "mua": "mưa",
        "it may": "ít mây",
        "nhieu may": "nhiều mây",
    }.get(summary, summary)


def format_weather_info(city=None):
    weather = get_weather_info(city)
    location = weather["location"]
    if weather.get("country"):
        location = f"{location}, {weather['country']}"

    icon = weather_icon(weather["summary"])
    summary = weather_summary_text(weather["summary"])

    return (
        f"Thời tiết tại {location}: {weather['temperature_c']} C, "
        f"cảm giác như {weather['feels_like_c']} C, "
        f"độ ẩm {weather['humidity']}%, "
        f"gió {weather['wind_kph']} km/h {weather['wind_dir']}, "
        f"{summary} ({weather['condition']}). {icon}".strip()
    )


def format_tomorrow_7am_forecast(city=None):
    forecast = get_tomorrow_7am_forecast(city)
    location = forecast["location"]
    if forecast.get("country"):
        location = f"{location}, {forecast['country']}"

    icon = weather_icon(forecast["summary"])
    summary = weather_summary_text(forecast["summary"])

    return (
        f"Dự báo thời tiết 7h sáng mai tại {location}: {forecast['temperature_c']} C, "
        f"cảm giác như {forecast['feels_like_c']} C, "
        f"độ ẩm {forecast['humidity']}%, "
        f"khả năng mưa {forecast['chance_of_rain']}%, "
        f"gió {forecast['wind_kph']} km/h {forecast['wind_dir']}, "
        f"{summary} ({forecast['condition']}). {icon}".strip()
    )


def format_tomorrow_day_forecast(city=None):
    forecast = get_tomorrow_day_forecast(city)
    location = forecast["location"]
    if forecast.get("country"):
        location = f"{location}, {forecast['country']}"

    icon = weather_icon(forecast["summary"])
    summary = weather_summary_text(forecast["summary"])

    return (
        f"Dự báo thời tiết cả ngày mai tại {location}: TB {forecast['temperature_c']} C "
        f"(cao {forecast['max_temp_c']} C / thấp {forecast['min_temp_c']} C), "
        f"độ ẩm {forecast['humidity']}%, "
        f"khả năng mưa {forecast['chance_of_rain']}%, "
        f"gió tối đa {forecast['wind_kph']} km/h, "
        f"{summary} ({forecast['condition']}). {icon}".strip()
    )


def main():
    print(json.dumps(get_weather_info(), ensure_ascii=False, indent=2))
    print()
    print(format_weather_info())
    print()
    print(json.dumps(get_tomorrow_7am_forecast(), ensure_ascii=False, indent=2))
    print()
    print(format_tomorrow_7am_forecast())


if __name__ == "__main__":
    main()
