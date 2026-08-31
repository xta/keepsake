require "test_helper"

# These assertions come from SPEC.md, not from the Python implementation.
# Where the two disagree the spec wins, and a second client written from the
# spec alone is what proves the spec is any good.
class Keepsake::MediaTest < ActiveSupport::TestCase
  M = Keepsake::Media

  test "a key is media only when its last segment has a dot and no leading dot" do
    assert M.has_extension?("IMG_0002.MOV")
    assert M.has_extension?("media/2026/a.mp4")
    assert_not M.has_extension?("README"), "no extension at all"
    assert_not M.has_extension?(".DS_Store"), "a leading dot marks it hidden"
    assert_not M.has_extension?(".bzEmpty")
    assert_not M.has_extension?(".hidden.mp4"), "the leading dot outranks the extension"
  end

  test "suffix case is insignificant" do
    assert_equal ".mov", M.extension_of("IMG_0002.MOV")
    assert_equal "a.mp4", M.media_key_for_sidecar("a.mp4.JSON")
    assert M.sidecar?("IMG_0002.MOV.JSON")
  end

  test "a thumbnail is a key formed by appending an image extension to a key that exists" do
    keys = [ "img3.jpg", "img3.jpg.jpg", "vacation.jpg", "clip.mp4", "clip.mp4.jpg" ]

    # The doubled extension looks like a mistake and is not one: the suffix is
    # appended to the complete filename, without exception.
    assert_equal "img3.jpg", M.thumbnail_of("img3.jpg.jpg", keys)
    assert_equal "clip.mp4", M.thumbnail_of("clip.mp4.jpg", keys)

    # Standalone media, because no key named "vacation" exists to own it.
    assert_nil M.thumbnail_of("vacation.jpg", keys)
  end

  test "companion keys append to the complete filename" do
    assert_equal "piano-recital.mp4.json", M.sidecar_key_for("piano-recital.mp4")
  end

  test "vacation.mp4 and vacation.mov can coexist" do
    assert_equal "vacation.mp4.json", M.sidecar_key_for("vacation.mp4")
    assert_equal "vacation.mov.json", M.sidecar_key_for("vacation.mov")
  end

  test "playability is decided by extension, never by contents" do
    assert M.playable?("a.mp4")
    assert M.playable?("a.webm")
    assert_not M.playable?("a.heic"), "no mainstream browser renders HEIC"
    assert_not M.playable?("a.avi")
    assert_not M.playable?("README")
  end
end
