"""The test setup behind a device and its sensor definitions.

    laptop (builderwars CLI) --USB--> FREE-WILi --I2C/SPI/UART/GPIO--> 1-4 target boards

* The CLI reports the laptop and the FREE-WILi when ``builderwars run`` starts
  (``report_connection``, any member who may upload board data).
* People add target boards and define each board's sensors in the web app
  (``add_board`` / ``add_sensor`` ..., ``device:configure``: the project owner for now).
* The CLI downloads the sensors (``list_sensors``) and reads each one through the FREE-WILi.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from application.ports import (
    DeviceRepository,
    DeviceSetupRepository,
    SensorRepository,
    TargetBoardRepository,
    UserDirectory,
)
from application.services.authorization import Authorizer
from device_protocol.sensors import MAX_SENSORS_PER_DEVICE, SensorSpec
from device_protocol.setup import SetupReport
from domain.common import ConflictError, NotFoundError, utcnow
from domain.devices import (
    MAX_TARGET_BOARDS,
    BoardInUseError,
    Device,
    DeviceSetup,
    RunSupersededError,
    Sensor,
    TargetBoard,
)
from domain.projects import Permission

MAX_BOARD_NAME = 120
# Uploads refresh the run's lock at most this often (it lapses after RUN_LOCK_TTL).
_TOUCH_EVERY = timedelta(seconds=15)
MAX_BOARD_NOTES = 2000


@dataclass(frozen=True, slots=True)
class SetupView:
    """Everything the device page shows about the chain."""

    setup: DeviceSetup
    boards: list[TargetBoard]
    sensors: list[Sensor]
    # The run holding the board right now, if any (the lock), and who started it.
    run_active: bool = False
    run_by_email: str | None = None


class DeviceSetupService:
    def __init__(
        self,
        devices: DeviceRepository,
        setups: DeviceSetupRepository,
        boards: TargetBoardRepository,
        sensors: SensorRepository,
        authorizer: Authorizer,
        *,
        users: UserDirectory | None = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self._users = users
        self._devices = devices
        self._setups = setups
        self._boards = boards
        self._sensors = sensors
        self._authorizer = authorizer
        self._clock = clock

    def _device(self, user_id: str, device_id: str, permission: Permission) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise NotFoundError("device", device_id)
        try:
            self._authorizer.require(user_id, device.project_id, permission)
        except NotFoundError:
            raise NotFoundError("device", device_id) from None
        return device

    def _setup(self, device_id: str) -> DeviceSetup:
        return self._setups.get(device_id) or DeviceSetup(device_id=device_id)

    # -- the whole picture ------------------------------------------------------------------
    def get_setup(self, *, user_id: str, device_id: str) -> SetupView:
        self._device(user_id, device_id, Permission.VIEW_PROJECT)
        setup = self._setup(device_id)
        active = setup.run_active_at(self._clock())
        email = self._email(setup.run_by) if active else None
        return SetupView(
            setup=setup,
            boards=self._boards.list_for_device(device_id),
            sensors=self._sensors.list_for_device(device_id),
            run_active=active,
            run_by_email=email,
        )

    def _email(self, user_id: str | None) -> str | None:
        if not user_id or self._users is None:
            return None
        try:
            user = self._users.get(user_id)
        except Exception:  # the directory is only for a friendlier label
            return None
        return user.email if user else None

    # -- laptop + FREE-WILi (reported by the CLI) -------------------------------------------
    def report_connection(
        self, *, user_id: str, device_id: str, report: SetupReport
    ) -> DeviceSetup:
        self._device(user_id, device_id, Permission.UPLOAD_DEVICE_DATA)
        now = self._clock()
        setup = self._setup(device_id)
        if report.run_id:  # lock the board for this run first: BoardInUseError if held
            try:
                setup = setup.claim_run(
                    report.run_id, by=user_id, at=now, take_over=report.take_over
                )
            except BoardInUseError:
                who = self._email(setup.run_by)
                raise BoardInUseError(f"this board is in use by {setup.holder_text(who)}") from None
        setup = setup.with_report(
            host=report.host.model_dump(mode="json"),
            bridge=report.bridge.model_dump(mode="json") if report.bridge else None,
            by=user_id,
            at=now,
        )
        self._setups.save(setup)
        return setup

    def release_run(self, *, user_id: str, device_id: str, run_id: str) -> None:
        """``builderwars run`` stopped: free the board (no-op if another run holds it)."""
        self._device(user_id, device_id, Permission.UPLOAD_DEVICE_DATA)
        setup = self._setups.get(device_id)
        if setup is not None and setup.run_id == run_id:
            self._setups.save(setup.release_run(run_id, at=self._clock()))

    def keep_run(self, *, user_id: str, device_id: str, run_id: str) -> None:
        """Data is arriving from ``run_id`` (before it is stored): keep its lock alive, or
        take the lock back if it had lapsed. ``RunSupersededError`` if another live run took
        the board over, so the old run stops instead of mixing its data in."""
        self._device(user_id, device_id, Permission.UPLOAD_DEVICE_DATA)
        now = self._clock()
        setup = self._setup(device_id)
        if setup.run_id != run_id and setup.run_active_at(now):
            who = self._email(setup.run_by)
            raise RunSupersededError(
                f"the board was taken over by {setup.holder_text(who)}; this run stops"
            )
        if setup.run_id == run_id and setup.run_seen_at and now - setup.run_seen_at < _TOUCH_EVERY:
            return  # fresh enough; skip a write per upload
        self._setups.save(setup.claim_run(run_id, by=user_id, at=now))

    # -- target boards (described by people) -----------------------------------------------
    def add_board(self, *, user_id: str, device_id: str, name: str, notes: str = "") -> TargetBoard:
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        if len(self._boards.list_for_device(device_id)) >= MAX_TARGET_BOARDS:
            raise ConflictError(
                f"a FREE-WILi can drive at most {MAX_TARGET_BOARDS} target boards; remove one first"
            )
        now = self._clock()
        board = TargetBoard(
            device_id=device_id,
            name=_board_name(name),
            notes=notes[:MAX_BOARD_NOTES],
            created_at=now,
            updated_at=now,
        )
        self._boards.add(board)
        return board

    def update_board(
        self, *, user_id: str, device_id: str, board_id: str, name: str, notes: str = ""
    ) -> TargetBoard:
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        board = replace(
            self._board_of(device_id, board_id),
            name=_board_name(name),
            notes=notes[:MAX_BOARD_NOTES],
            updated_at=self._clock(),
        )
        self._boards.save(board)
        return board

    def delete_board(self, *, user_id: str, device_id: str, board_id: str) -> None:
        """Removes the board and its sensors."""
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        self._board_of(device_id, board_id)
        self._boards.delete(board_id)

    def _board_of(self, device_id: str, board_id: str) -> TargetBoard:
        board = self._boards.get(board_id)
        if board is None or board.device_id != device_id:
            raise NotFoundError("target board", board_id)
        return board

    # -- sensors -----------------------------------------------------------------------------
    def list_sensors(self, *, user_id: str, device_id: str) -> list[Sensor]:
        self._device(user_id, device_id, Permission.VIEW_PROJECT)
        return self._sensors.list_for_device(device_id)

    def add_sensor(
        self, *, user_id: str, device_id: str, board_id: str, spec: SensorSpec
    ) -> Sensor:
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        self._board_of(device_id, board_id)
        if len(self._sensors.list_for_device(device_id)) >= MAX_SENSORS_PER_DEVICE:
            raise ConflictError(
                f"a device can have at most {MAX_SENSORS_PER_DEVICE} sensors; remove one first"
            )
        now = self._clock()
        sensor = Sensor(
            device_id=device_id,
            board_id=board_id,
            created_at=now,
            updated_at=now,
            **_fields(spec),  # type: ignore[arg-type]
        )
        self._sensors.add(sensor)
        return sensor

    def update_sensor(
        self,
        *,
        user_id: str,
        device_id: str,
        sensor_id: str,
        board_id: str,
        spec: SensorSpec,
    ) -> Sensor:
        """Replace the definition; moving it to another of the device's boards is allowed."""
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        current = self._sensor_of(device_id, sensor_id)
        self._board_of(device_id, board_id)
        sensor = replace(
            current,
            board_id=board_id,
            updated_at=self._clock(),
            **_fields(spec),  # type: ignore[arg-type]
        )
        self._sensors.save(sensor)
        return sensor

    def delete_sensor(self, *, user_id: str, device_id: str, sensor_id: str) -> None:
        self._device(user_id, device_id, Permission.CONFIGURE_DEVICE)
        self._sensor_of(device_id, sensor_id)
        self._sensors.delete(sensor_id)

    def _sensor_of(self, device_id: str, sensor_id: str) -> Sensor:
        sensor = self._sensors.get(sensor_id)
        if sensor is None or sensor.device_id != device_id:
            raise NotFoundError("sensor", sensor_id)
        return sensor


def _board_name(name: str) -> str:
    name = name.strip()[:MAX_BOARD_NAME]
    if not name:
        raise ValueError("a target board needs a name")
    return name


def _fields(spec: SensorSpec) -> dict[str, object]:
    return {
        "key": spec.key,
        "name": spec.name,
        "unit": spec.unit,
        "poll_interval_s": spec.poll_interval_s,
        "enabled": spec.enabled,
        "bus": spec.bus.model_dump(mode="json"),
        "decode": spec.decode.model_dump(mode="json"),
    }


def sensor_spec(sensor: Sensor) -> SensorSpec:
    """The stored sensor as the shared model (what the CLI receives)."""
    return SensorSpec.model_validate(
        {
            "key": sensor.key,
            "name": sensor.name,
            "unit": sensor.unit,
            "poll_interval_s": sensor.poll_interval_s,
            "enabled": sensor.enabled,
            "bus": sensor.bus,
            "decode": sensor.decode,
        }
    )
