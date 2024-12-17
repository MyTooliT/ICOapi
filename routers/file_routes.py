import pandas
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.params import Depends
from fastapi.responses import FileResponse
import os
from datetime import datetime
from models.models import Dataset, MeasurementFileDetails, ParsedMeasurement
from scripts.file_handling import get_measurement_dir, is_dangerous_filename
import pandas as pd
router = APIRouter(prefix="/files")


@router.get("")
async def list_files(measurement_dir: str = Depends(get_measurement_dir)) -> list[MeasurementFileDetails]:
    try:
        files_info: list[MeasurementFileDetails] = []
        # Iterate over files in the directory
        for filename in os.listdir(measurement_dir):
            file_path = os.path.join(measurement_dir, filename)
            if os.path.isfile(file_path):
                # Get file creation time and size
                creation_time = datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                file_size = os.path.getsize(file_path)

                details = MeasurementFileDetails(
                    name=filename,
                    size=file_size,
                    created=creation_time
                )
                files_info.append(details)
        return files_info
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}")
async def download_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    full_path = os.path.join(measurement_dir, name)
    print(full_path)
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=name)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@router.delete("/{name}")
async def delete_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
            return {"detail": f"File '{name}' deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="File not found")


@router.get("/analyze/{name}")
async def get_analyzed_file(name: str, measurement_dir: str = Depends(get_measurement_dir)) -> ParsedMeasurement:
    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    if os.path.isfile(os.path.join(measurement_dir, name)):
        data = pd.read_hdf(os.path.join(measurement_dir, name), key="acceleration")
        try:
            df = ensure_dataframe_with_columns(data, {"counter", "timestamp", "x"})
        except TypeError:
            raise HTTPException(status_code=404, detail="File not readable")
        except ValueError:
            raise HTTPException(status_code=404, detail=f"Missing data columns")

        df_dict = df.to_dict(orient="list")
        datasets = df_dict.copy()
        datasets.__delitem__("timestamp")
        datasets.__delitem__("counter")

        return ParsedMeasurement(
            counter=df_dict["counter"],
            timestamp=df_dict["timestamp"],
            datasets=[Dataset(name=key, data=values) for key, values in datasets.items()],
        )

    else:
        raise HTTPException(status_code=404, detail="File not found")


@router.post("/analyze")
async def post_analyzed_file(file: UploadFile, measurement_dir: str = Depends(get_measurement_dir)) -> ParsedMeasurement:
    file_path = os.path.join(measurement_dir, f"{file.filename}_TEMP")
    print(file_path)
    with open(file_path, "wb") as f:
        f.write(file.file.read())

    data = pd.read_hdf(file_path, key="acceleration")
    os.remove(file_path)

    try:
        df = ensure_dataframe_with_columns(data, {"counter", "timestamp", "x"})
    except TypeError:
        raise HTTPException(status_code=404, detail="File not readable")
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Missing data columns")

    df_dict = df.to_dict(orient="list")
    datasets = df_dict.copy()
    datasets.__delitem__("timestamp")
    datasets.__delitem__("counter")

    return ParsedMeasurement(
        counter=df_dict["counter"],
        timestamp=df_dict["timestamp"],
        datasets=[Dataset(name=key, data=values) for key, values in datasets.items()],
    )

def ensure_dataframe_with_columns(df, required_columns) -> pd.DataFrame:
    """
    Ensures the object is a DataFrame and contains the required columns.

    Parameters:
        df: The object to check.
        required_columns: A list or set of column names that must be present.

    Returns:
        The DataFrame if it meets the requirements.

    Raises:
        TypeError: If the object is not a DataFrame.
        ValueError: If required columns are missing.
    """
    # Ensure the object is a DataFrame
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected a pandas DataFrame, but got {type(df).__name__}")

    # Check for required columns
    missing_columns = set(required_columns) - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    return df