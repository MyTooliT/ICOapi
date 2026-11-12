"""Test protection of a running measurement against other clients

Several clients (e.g. people accessing the same edge device remotely) can
use the API at the same time. Actions of one client must not break the
measurement another client started.
"""

# -- Imports ------------------------------------------------------------------

from asyncio import gather, sleep
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from pytest import fixture, mark

from icoapi.models.globals import MeasurementSingleton
from icoapi.models.models import (
    MeasurementInstructionChannel,
    MeasurementInstructions,
)
from icoapi.routers import measurement_routes

# -- Fixtures -----------------------------------------------------------------


@fixture(name="running_measurement")
def fixture_running_measurement() -> Iterator[None]:
    """Pretend that a measurement is running"""

    measurement_state = MeasurementSingleton.get_instance()
    measurement_state.running = True
    try:
        yield
    finally:
        measurement_state.running = False


# -- Tests --------------------------------------------------------------------


class TestRunningMeasurementProtection:
    """Actions that would interfere with a running measurement"""

    @mark.parametrize(
        "method, path",
        [
            ("put", "can/connect"),
            ("put", "can/disconnect"),
            ("put", "reset-can"),
            ("get", "sth"),
        ],
    )
    def test_rejected_while_running(
        self,
        method: str,
        path: str,
        client,
        running_measurement,  # pylint: disable=unused-argument
    ) -> None:
        """The CAN connection must not be changed or scanned"""

        response = getattr(client, method)(path)

        assert response.status_code == 409
        assert "measurement is running" in response.json()["detail"]

    def test_state_still_available_while_running(
        self,
        state_prefix,
        client,
        running_measurement,  # pylint: disable=unused-argument
    ) -> None:
        """Reading the state is what other clients need, it stays possible"""

        response = client.get(state_prefix)

        assert response.status_code == 200
        assert response.json()["measurement_status"]["running"] is True


class TestConcurrentStart:  # pylint: disable=too-few-public-methods
    """Starting measurements from several clients at the same time"""

    async def test_only_one_measurement_starts(
        self, monkeypatch, tmp_path
    ) -> None:
        """Only one of two simultaneous starts may start a measurement

        Reading name and supply voltage from the sensor device takes a
        moment, which leaves time for a second start in between.
        """

        async def slow_name() -> str:
            await sleep(0.05)
            return "Test-STH"

        async def run_measurement(*_args: Any) -> None:
            await sleep(0)

        system = MagicMock()
        system.sensor_node.get_name = slow_name
        system.sensor_node.get_supply_voltage = AsyncMock(return_value=3.3)
        messenger = MagicMock()
        messenger.push_messenger_update = AsyncMock()
        monkeypatch.setattr(
            measurement_routes, "run_measurement", run_measurement
        )
        monkeypatch.setattr(
            measurement_routes, "get_measurement_dir", lambda: str(tmp_path)
        )

        instructions = MeasurementInstructions(
            name="Concurrent",
            mac_address="00-11-22-33-44-55",
            time=1,
            first=MeasurementInstructionChannel(sensor_id=None),
            second=MeasurementInstructionChannel(sensor_id=None),
            third=MeasurementInstructionChannel(sensor_id=None),
            ift_requested=False,
            ift_channel="",
            ift_window_width=50,
            adc=None,
            meta=None,
        )
        measurement_state = MeasurementSingleton.get_instance()
        try:
            results = await gather(
                *(
                    # pylint: disable-next=protected-access
                    measurement_routes._begin_measurement(
                        instructions,
                        MagicMock(),
                        system,
                        measurement_state,
                        messenger,
                    )
                    for _ in range(2)
                ),
                return_exceptions=True,
            )
        finally:
            await measurement_state.reset()

        started = [
            result
            for result in results
            if not isinstance(result, BaseException)
        ]
        rejected = [
            result for result in results if isinstance(result, HTTPException)
        ]
        assert len(started) == 1
        assert len(rejected) == 1
        assert rejected[0].status_code == 400
