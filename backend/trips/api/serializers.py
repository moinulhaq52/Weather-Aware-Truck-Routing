"""Input validation for the public API. Every field is bounded so requests can't be abused."""

import time

from rest_framework import serializers


class GeocodeQuerySerializer(serializers.Serializer):
    q = serializers.CharField(min_length=2, max_length=200, trim_whitespace=True)


MAX_LOAD_LB = 80_000  # US federal gross vehicle weight limit without special permits
DEPARTURE_PAST_GRACE_S = 3600
DEPARTURE_MAX_AHEAD_S = 7 * 86400


class PlaceSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)
    label = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class PlanRequestSerializer(serializers.Serializer):
    origin = PlaceSerializer()
    destination = PlaceSerializer()
    departure_time = serializers.DateTimeField(
        help_text="ISO-8601 with a UTC offset, e.g. 2026-11-04T08:00:00-06:00"
    )
    load_weight_lb = serializers.FloatField(min_value=1, max_value=MAX_LOAD_LB)
    interval_miles = serializers.ChoiceField(choices=[10, 25, 50])
    simulate_storm = serializers.BooleanField(default=False)  # extra E3
    hos = serializers.BooleanField(default=False)  # extra E5

    def validate_departure_time(self, value):
        # Reject naive datetimes: guessing the driver's time zone would shift every ETA.
        raw = str(self.initial_data.get("departure_time", ""))
        if not (raw.endswith("Z") or "+" in raw[10:] or "-" in raw[10:]):
            raise serializers.ValidationError("Include a UTC offset, e.g. 2026-11-04T08:00-06:00.")
        now = time.time()
        ts = value.timestamp()
        if ts < now - DEPARTURE_PAST_GRACE_S:
            raise serializers.ValidationError("Departure time is in the past.")
        if ts > now + DEPARTURE_MAX_AHEAD_S:
            raise serializers.ValidationError("Departure must be within the next 7 days.")
        return value
