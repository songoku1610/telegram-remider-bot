import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from dotenv import load_dotenv


load_dotenv()

GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"
CURRENT_CONDITIONS_URL = "https://weather.googleapis.com/v1/currentConditions:lookup"


class GoogleAPIError(RuntimeError):
    def __init__(self, message, status_code=None, api_status=None):
        super().__init__(message)
        self.status_code = status_code
        self.api_status = api_status


class GoogleWeatherUnsupportedLocation(GoogleAPIError):
    pass


def _load_google_weather_config():
    api_key = os.getenv("GOOGLE_API_KEY")
    city = os.getenv("WEATHER_CITY") or os.getenv("WEATHER_LOCATION")

    if not api_key:
        raise ValueError("Missing GOOGLE_API_KEY in .env")
    if not city:
        raise ValueError("Missing WEATHER_CITY in .env")

    return api_key, city


def _get_json(url):
    try:
        with urlopen(url, timeout=10) as response:
            return json.load(response)
    except HTTPError as exc:
        api_status = None
        try:
            detail = exc.read().decode("utf-8", errors="replace")
            error_data = json.loads(detail)
            error = error_data.get("error", {})
            api_status = error.get("status")
            message = error.get("message") or detail
        except Exception:
            detail = exc.reason
            message = str(detail)

        raise GoogleAPIError(
            f"Google API request failed: HTTP {exc.code} - {message}",
            status_code=exc.code,
            api_status=api_status,
        ) from exc
    except URLError as exc:
        raise GoogleAPIError(f"Google API request failed: {exc.reason}") from exc


def geocode_city(city=None, api_key=None):
    if api_key is None:
        api_key, default_city = _load_google_weather_config()
        city = city or default_city

    query = urlencode(
        {
            "address": city,
            "key": api_key,
            "language": "vi",
        }
    )
    data = _get_json(f"{GEOCODING_URL}?{query}")

    if data.get("status") != "OK" or not data.get("results"):
        message = data.get("error_message") or data.get("status") or "No geocoding result"
        raise RuntimeError(f"Cannot geocode city '{city}': {message}")

    result = data["results"][0]
    location = result["geometry"]["location"]
    return {
        "name": result.get("formatted_address", city),
        "latitude": location["lat"],
        "longitude": location["lng"],
    }


def classify_weather(condition_type, condition_text, cloud_cover, precip_quantity, is_daytime):
    condition = (condition_type or "").upper()
    text = (condition_text or "").lower()

    if precip_quantity > 0 or any(
        word in condition or word in text
        for word in ["RAIN", "DRIZZLE", "STORM", "THUNDER", "SHOWER", "mua"]
    ):
        return "mua"
    if "PARTLY" in condition:
        return "it may"
    if cloud_cover >= 70 or "CLOUDY" in condition or "OVERCAST" in condition:
        return "nhieu may"
    if cloud_cover >= 30:
        return "it may"
    if "CLEAR" in condition or "SUNNY" in condition or "nang" in text:
        return "nang" if is_daytime else "troi quang"

    return "nang" if is_daytime else "troi quang"


def get_weather_info(city=None):
    api_key, default_city = _load_google_weather_config()
    requested_city = city or default_city
    place = geocode_city(requested_city, api_key)

    query = urlencode(
        {
            "key": api_key,
            "location.latitude": place["latitude"],
            "location.longitude": place["longitude"],
            "unitsSystem": "METRIC",
            "languageCode": "vi",
        }
    )
    try:
        data = _get_json(f"{CURRENT_CONDITIONS_URL}?{query}")
    except GoogleAPIError as exc:
        if exc.status_code == 404 and exc.api_status == "NOT_FOUND":
            raise GoogleWeatherUnsupportedLocation(
                "Google Weather API does not support current weather for "
                f"'{place['name']}' ({place['latitude']}, {place['longitude']})."
            ) from exc
        raise

    weather_condition = data.get("weatherCondition", {})
    description = weather_condition.get("description", {})
    precipitation = data.get("precipitation", {})
    qpf = precipitation.get("qpf", {})
    wind = data.get("wind", {})
    wind_speed = wind.get("speed", {})
    temperature = data.get("temperature", {})
    feels_like = data.get("feelsLikeTemperature", {})
    cloud_cover = data.get("cloudCover", 0)
    precip_quantity = qpf.get("quantity", 0)
    is_daytime = data.get("isDaytime", True)

    return {
        "location": place["name"],
        "latitude": place["latitude"],
        "longitude": place["longitude"],
        "current_time": data.get("currentTime"),
        "temperature_c": temperature.get("degrees"),
        "feels_like_c": feels_like.get("degrees"),
        "humidity": data.get("relativeHumidity"),
        "uv_index": data.get("uvIndex"),
        "wind_kph": wind_speed.get("value"),
        "condition": description.get("text", ""),
        "condition_type": weather_condition.get("type", ""),
        "cloud": cloud_cover,
        "precip_mm": precip_quantity,
        "summary": classify_weather(
            weather_condition.get("type", ""),
            description.get("text", ""),
            cloud_cover,
            precip_quantity,
            is_daytime,
        ),
    }


def format_weather_info(city=None):
    weather = get_weather_info(city)
    feels_like = weather["feels_like_c"]
    humidity = weather["humidity"]

    extra_parts = []
    if feels_like is not None:
        extra_parts.append(f"cam giac nhu {feels_like} C")
    if humidity is not None:
        extra_parts.append(f"do am {humidity}%")

    extra = f", {', '.join(extra_parts)}" if extra_parts else ""

    return (
        f"Thoi tiet tai {weather['location']}: {weather['temperature_c']} C"
        f"{extra}, gio {weather['wind_kph']} km/h, "
        f"{weather['summary']} ({weather['condition']})."
    )
