import filecmp
from pathlib import Path
from utsu_std.database import preprocess_uoft_csv


def test_uoft_csv_importing():
    test_file = Path("./test_data/fake_uoft_data.csv")
    expected_file = Path("./test_data/fake_uoft_data_processed.csv")

    # run test
    processed_file = preprocess_uoft_csv(test_file)

    # files should be byte-byte same
    test = filecmp.cmp(processed_file, expected_file, shallow=False)

    # delete processed
    #processed_file.unlink(missing_ok=True)

    assert test == True


def test_missing_req():
    broken_file = Path("./test_data/missing_req_fake_uoft_data.csv")
    test = False

    # run test
    try:
        processed_file = preprocess_uoft_csv(broken_file)
    except ValueError as e:
        test = True

    assert test



if __name__ == "__main__":
    test_uoft_csv_importing()
    test_missing_req()