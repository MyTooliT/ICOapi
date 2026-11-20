"""Tests for writing measurement files in a thread of their own"""

# -- Imports ------------------------------------------------------------------

import asyncio
import threading
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import h5py
import numpy as np
from icoschema import DatasetBundle
from icoschema.v2 import (
    BundleWriter,
    ChannelMetadata,
    LinearConversion,
    Sensor,
    SourceSpec,
)
from icoschema.v2.storage.writer import SourceWriter
from pytest import MonkeyPatch, raises

from icoapi.scripts import writer_thread
from icoapi.scripts.writer_thread import ThreadedBundleWriter, WriterError

# -- Functions ----------------------------------------------------------------


def spec(name: str = "a", channels: int = 3, **changes: Any) -> SourceSpec:
    """Create the description of a source"""

    return SourceSpec(
        name=name,
        channels=[
            ChannelMetadata(
                sensor=Sensor(sensor_id=f"s{number}", unit="g"),
                conversion=LinearConversion(gain=1.0, offset=0.0),
            )
            for number in range(channels)
        ],
        start_time="2026-11-14T10:00:00.000000",
        **changes,
    )


def sources(path: Path) -> dict[str, Any]:
    """Read the sources of a bundle"""

    recording: Any = DatasetBundle.from_hdf5(str(path)).recording
    return dict(recording.sources)


def fill(source: Any, rows: int, first: int = 0) -> None:
    """Add rows (timestamp, three values and counter depend on the number)"""

    for number in range(first, first + rows):
        source.append_row(
            number * 100,
            [float(number), float(number) + 0.5, -float(number)],
            number % 256,
        )


# -- Tests --------------------------------------------------------------------


def test_data_is_written(tmp_path: Path) -> None:
    """All rows of all sources are in the file, in order"""

    path = tmp_path / "data.hdf5"
    with ThreadedBundleWriter(
        str(path), [spec("a"), spec("b", channels=1)], block_rows=100
    ) as writer:
        fill(writer["a"], 1050)
        for number in range(250):
            writer["b"].append_row(number, [float(number)], number % 256)

    stored = sources(path)
    assert len(stored["a"].timestamps) == 1050
    assert stored["a"].timestamps.tolist() == [n * 100 for n in range(1050)]
    assert stored["a"].channel2.tolist() == [n + 0.5 for n in range(1050)]
    assert stored["a"].counter.tolist() == [n % 256 for n in range(1050)]
    assert stored["b"].channel_count == 1
    assert stored["b"].channel1.tolist() == [float(n) for n in range(250)]


def test_short_blocks_are_written(tmp_path: Path) -> None:
    """Rows that do not fill a block are written when the file is closed"""

    path = tmp_path / "short.hdf5"
    with ThreadedBundleWriter(str(path), [spec()], block_rows=1000) as writer:
        fill(writer["a"], 3)

    assert sources(path)["a"].timestamps.tolist() == [0, 100, 200]


def test_attributes_and_pictures(tmp_path: Path) -> None:
    """Updates and pictures are stored, in order with the data"""

    path = tmp_path / "meta.hdf5"
    with ThreadedBundleWriter(str(path), [spec()], block_rows=10) as writer:
        writer.add_picture("pre__pictures", ["aGk="])
        writer.flush()
        writer["a"].update(start_time="2026-01-02T03:04:05.000006")
        fill(writer["a"], 25)
        writer["a"].update(additional_data='{"done": true}')

    stored = DatasetBundle.from_hdf5(str(path))
    source = sources(path)["a"]
    assert source.recording_metadata.start_time == "2026-01-02T03:04:05.000006"
    assert source.additional_data == '{"done": true}'
    assert stored.pictures == {"pre__pictures": ["aGk="]}  # type: ignore[attr-defined]


def test_the_file_is_written_by_another_thread(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Writing does not happen in the thread that adds the rows"""

    threads: set[int] = set()
    original = SourceWriter.append

    def append(self: SourceWriter, *arguments: Any, **keywords: Any) -> None:
        threads.add(threading.get_ident())
        original(self, *arguments, **keywords)

    monkeypatch.setattr(SourceWriter, "append", append)
    with ThreadedBundleWriter(
        str(tmp_path / "thread.hdf5"), [spec()], block_rows=10
    ) as writer:
        fill(writer["a"], 100)

    assert len(threads) == 1
    assert threading.get_ident() not in threads


def test_file_is_closed_and_complete_after_exception(tmp_path: Path) -> None:
    """Leaving the block with an exception still writes everything"""

    path = tmp_path / "exception.hdf5"
    with (
        raises(RuntimeError),
        ThreadedBundleWriter(str(path), [spec()], block_rows=10) as writer,
    ):
        fill(writer["a"], 35)
        raise RuntimeError("failed")

    assert len(sources(path)["a"].timestamps) == 35


def test_closing_twice(tmp_path: Path) -> None:
    """A writer can be closed again and refuses more data"""

    writer = ThreadedBundleWriter(str(tmp_path / "twice.hdf5"), [spec()])
    fill(writer["a"], 3)
    writer.close()
    writer.close()

    with raises(WriterError, match="closed"):
        writer.add_picture("x", [])


def test_file_that_can_not_be_created(tmp_path: Path) -> None:
    """The error of creating the file is raised where the writer is created"""

    with raises(OSError):
        ThreadedBundleWriter(str(tmp_path / "missing" / "a.hdf5"), [spec()])
    assert threading.active_count() == 1 or all(
        not thread.name.startswith("writer ")
        for thread in threading.enumerate()
    )


def test_invalid_sources(tmp_path: Path) -> None:
    """Invalid sources are refused like by the writer of ICOschema"""

    with raises(ValueError, match="duplicate"):
        ThreadedBundleWriter(str(tmp_path / "x.hdf5"), [spec("a"), spec("a")])


def test_failure_of_the_writer_thread(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """If the data can not be written, adding data fails"""

    original = SourceWriter.append
    calls = []

    def append(self: SourceWriter, *arguments: Any, **keywords: Any) -> None:
        calls.append(1)
        if len(calls) == 2:
            raise OSError("No space left on device")
        original(self, *arguments, **keywords)

    monkeypatch.setattr(SourceWriter, "append", append)
    writer = ThreadedBundleWriter(
        str(tmp_path / "full.hdf5"), [spec()], block_rows=10
    )

    with raises(WriterError, match="No space left on device") as error:
        for number in range(100_000):
            writer["a"].append_row(number, [1.0, 2.0, 3.0], number % 256)
            if number % 10 == 0:
                sleep(0.001)  # Let the thread work
    assert isinstance(error.value.__cause__, OSError)

    # Closing works and reports the problem; the thread is gone
    with raises(WriterError, match="No space left on device"):
        writer.close()
    assert not writer._thread.is_alive()


def test_disk_that_is_too_slow(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Data does not pile up without limit"""

    release = threading.Event()
    original = SourceWriter.append

    def append(self: SourceWriter, *arguments: Any, **keywords: Any) -> None:
        release.wait(10)
        original(self, *arguments, **keywords)

    monkeypatch.setattr(SourceWriter, "append", append)
    writer = ThreadedBundleWriter(
        str(tmp_path / "slow.hdf5"), [spec()], block_rows=10, queue_blocks=5
    )

    try:
        with raises(WriterError, match="too slow"):
            fill(writer["a"], 10 * 20)
    finally:
        release.set()
    # The error stays: Rows were lost, so nothing more is written
    with raises(WriterError, match="too slow"):
        writer.flush()
    with raises(WriterError, match="too slow"):
        fill(writer["a"], 10)
    # The file is closed and valid (how much of the data is in it depends on
    # how far the writer thread got, before it was clear that data is lost)
    with raises(WriterError, match="too slow"):
        writer.close()
    with h5py.File(tmp_path / "slow.hdf5") as file:
        assert len(file["recording"][()]) <= 10 * 20  # type: ignore[arg-type]


def test_close_waits_for_everything(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """Closing waits for data that is still waiting to be written"""

    original = SourceWriter.append

    def append(self: SourceWriter, *arguments: Any, **keywords: Any) -> None:
        sleep(0.02)
        original(self, *arguments, **keywords)

    monkeypatch.setattr(SourceWriter, "append", append)
    path = tmp_path / "wait.hdf5"
    writer = ThreadedBundleWriter(str(path), [spec()], block_rows=10)
    fill(writer["a"], 200)
    writer.close()

    assert len(sources(path)["a"].timestamps) == 200


def test_periodic_flush(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """The file is flushed from time to time, even without new data"""

    monkeypatch.setattr(writer_thread, "FLUSH_INTERVAL", 0.1)
    flushes = []
    original = BundleWriter.flush

    def flush(self: BundleWriter) -> None:
        flushes.append(1)
        original(self)

    monkeypatch.setattr(BundleWriter, "flush", flush)
    with ThreadedBundleWriter(
        str(tmp_path / "flush.hdf5"), [spec()], block_rows=10
    ) as writer:
        fill(writer["a"], 20)
        sleep(1.0)

    # A flush takes a while (the file is synced to disk), so not every 0.1
    # seconds, but regularly
    assert len(flushes) >= 3


async def test_slow_disk_does_not_hold_the_loop_up(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    """A disk that is slow for a moment does not stop the event loop"""

    # What both ways of writing end in
    original = SourceWriter._write_rows

    def write_rows(self: SourceWriter, rows: Any) -> None:
        sleep(0.05)
        original(self, rows)

    monkeypatch.setattr(SourceWriter, "_write_rows", write_rows)

    async def measure(source: Any) -> float:
        """Add data like a stream, return the longest delay of the loop"""

        delays: list[float] = []
        stop = False

        async def ticker() -> None:
            while not stop:
                before = perf_counter()
                await asyncio.sleep(0.002)
                delays.append(perf_counter() - before - 0.002)

        task = asyncio.create_task(ticker())
        for block in range(10):
            fill(source, 64, first=block * 64)
            await asyncio.sleep(0.002)
        stop = True
        await task
        return max(delays)

    with BundleWriter(
        str(tmp_path / "inline.hdf5"), [spec()], chunk_rows=64
    ) as direct:
        inline = await measure(direct["a"])
    with ThreadedBundleWriter(
        str(tmp_path / "thread.hdf5"), [spec()], block_rows=64
    ) as threaded:
        thread = await measure(threaded["a"])

    # Writing in the loop stops it for as long as a write takes
    assert inline >= 0.045
    assert thread < 0.02
    assert len(sources(tmp_path / "thread.hdf5")["a"].timestamps) == 640


def test_same_file_as_writer_of_icoschema(tmp_path: Path) -> None:
    """The file is the one a ``BundleWriter`` writes"""

    direct, threaded = tmp_path / "direct.hdf5", tmp_path / "threaded.hdf5"
    with BundleWriter(str(direct), [spec()]) as writer:
        fill(writer["a"], 500)
    with ThreadedBundleWriter(
        str(threaded), [spec()], block_rows=64
    ) as threaded_writer:
        fill(threaded_writer["a"], 500)

    first, second = sources(direct)["a"], sources(threaded)["a"]
    for column in (
        "timestamps",
        "counter",
        "channel1",
        "channel2",
        "channel3",
    ):
        np.testing.assert_array_equal(
            getattr(first, column), getattr(second, column)
        )
    assert first.hardware_metadata == second.hardware_metadata


def test_append_rows_equals_append_row(tmp_path: Path) -> None:
    """Adding many rows at once must store the same as adding them one by one"""

    rows = 5000  # More than two blocks
    numbers = np.arange(rows)
    timestamps = numbers * 100
    values = np.column_stack([numbers, numbers + 0.5, -numbers]).astype(float)
    counters = numbers % 256

    with ThreadedBundleWriter(
        str(tmp_path / "single.hdf5"), [spec()], block_rows=2048
    ) as writer:
        for index in range(rows):
            writer["a"].append_row(
                int(timestamps[index]),
                list(values[index]),
                int(counters[index]),
            )
    with ThreadedBundleWriter(
        str(tmp_path / "batch.hdf5"), [spec()], block_rows=2048
    ) as writer:
        writer["a"].append_rows(
            timestamps[:3000], values[:3000], counters[:3000]
        )
        writer["a"].append_rows(
            timestamps[3000:], values[3000:], counters[3000:]
        )

    expected = sources(tmp_path / "single.hdf5")["a"]
    result = sources(tmp_path / "batch.hdf5")["a"]
    assert len(result.timestamps) == rows
    for name in ("timestamps", "counter", "channel1", "channel2", "channel3"):
        assert np.array_equal(getattr(expected, name), getattr(result, name))


def test_recorder_batch_equals_single_messages(tmp_path: Path) -> None:
    """Storing messages in batches gives the data and statistics of one by one"""

    from icotronic.can.streaming import StreamingConfiguration, StreamingData

    from icoapi.scripts.recording import SourceRecorder

    counters = [1, 2, 3, 7, 8, 8, 12, 255, 0, 1, 5]
    timestamps = [index * 0.001 for index in range(len(counters))]
    values = [
        [float(index), index + 0.25, -float(index)] for index in range(11)
    ]

    def record(name: str, batched: bool) -> tuple[Any, float]:
        path = tmp_path / name
        with ThreadedBundleWriter(str(path), [spec(channels=1)]) as writer:
            recorder = SourceRecorder(
                writer["a"], StreamingConfiguration(first=True)
            )
            if batched:
                recorder.add_streaming_batch(
                    np.array(counters[:4], dtype=np.int64),
                    np.array(timestamps[:4]),
                    np.array(values[:4]),
                )
                recorder.add_streaming_batch(
                    np.array(counters[4:], dtype=np.int64),
                    np.array(timestamps[4:]),
                    np.array(values[4:]),
                )
            else:
                for counter, timestamp, value in zip(
                    counters, timestamps, values, strict=False
                ):
                    recorder.add_streaming_data(
                        StreamingData(counter, timestamp, list(value))
                    )
            loss = recorder.dataloss()
        return sources(path)["a"], loss

    single, single_loss = record("single.hdf5", False)
    batch, batch_loss = record("batch.hdf5", True)
    assert single_loss == batch_loss
    assert single_loss > 0
    for name in ("timestamps", "counter", "channel1"):
        assert np.array_equal(getattr(single, name), getattr(batch, name))
