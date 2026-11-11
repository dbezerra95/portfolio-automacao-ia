import numpy as np

from soil_zones.processing import classify, clean_patches, relative_ndvi, sampling_points


def test_median_normalization_and_clouds():
    field = np.array([[True, True], [True, False]])
    seasons = np.array([[[[.2, .4], [np.nan, .9]], [[.4, .2], [np.nan, .9]]], [[[.4, .8], [np.nan, .9]], [[.8, .4], [np.nan, .9]]]])
    result = relative_ndvi(seasons, field)
    np.testing.assert_allclose(result[0], [1, 1])
    assert np.isnan(result[1]).all()


def test_zones_are_ordered_stable_and_points_inside():
    index = np.tile(np.repeat([.7, 1., 1.3], 10), (20, 1))
    field = np.ones(index.shape, bool)
    zones = classify(index, field)
    np.testing.assert_array_equal(zones, classify(index, field))
    assert [zones[0, i] for i in (0, 10, 20)] == [1, 2, 3]
    for zone, y, x in sampling_points(zones):
        assert zones[y, x] == zone


def test_small_patch_cleanup_preserves_mask():
    zones = np.ones((10, 10), dtype=int)
    zones[5, 5] = 2
    zones[0, 0] = 0
    cleaned = clean_patches(zones, 3)
    assert cleaned[5, 5] == 1
    assert cleaned[0, 0] == 0


def test_uniform_field_one_zone():
    index = np.full((10, 10), .8)
    zones = classify(index, np.ones_like(index, dtype=bool))
    assert np.unique(zones).tolist() == [1]
    assert len(sampling_points(zones)) == 1


def test_track_exclusions_and_largest_patch_sampling():
    from scipy import ndimage
    from soil_zones.processing import usable_field

    y, x = np.indices((101, 101))
    field = (y - 50)**2 + (x - 50)**2 <= 48**2
    usable = usable_field(field, 10, center_radius=40, edge_buffer=20)
    index = np.ones(field.shape)
    index[15:35, 25:45] = .6
    index[50, 50:95] = .6
    index[65:85, 55:75] = 1.4
    zones = classify(index, usable, min_pixels=25)
    assert set(np.unique(zones)) == {0, 1, 2, 3}
    assert zones[20, 30] == 1
    assert zones[50, 80] != 1
    points = sampling_points(zones)
    for zone, row, col in points:
        assert usable[row, col]
        assert not (row == 50 and 50 <= col < 95)
        assert np.hypot(row - 50, col - 50) * 10 >= 40
        assert ndimage.distance_transform_edt(np.pad(field, 1))[row + 1, col + 1] * 10 > 20
        components, _ = ndimage.label(zones == zone)
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        assert sizes[components[row, col]] == sizes.max()
