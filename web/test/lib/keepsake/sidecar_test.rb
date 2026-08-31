require "test_helper"

class Keepsake::SidecarTest < ActiveSupport::TestCase
  S = Keepsake::Sidecar

  test "a stub records only what the bucket knows" do
    stub = S.build_stub("media/2026/IMG_0002.MOV", size_bytes: 1234, last_modified: Time.utc(2026, 5, 1, 9, 30))

    assert_equal 1, stub["schema"]
    assert_equal "IMG_0002.MOV", stub["file"]
    assert_equal "2026-05-01T09:30:00Z", stub["uploaded_at"]
    assert_equal 1234, stub["size_bytes"]
    assert_equal "video/quicktime", stub["media_type"]

    # The point of the whole design: nothing is guessed.
    assert_not stub.key?("title")
    assert_not stub.key?("recorded_at")
    assert_not stub.key?("tags")
  end

  test "merging preserves fields this app has never heard of" do
    # SPEC: "A writer that does not recognize a field must carry it through
    # unchanged on write." This is what lets clients of different versions
    # coexist without coordination.
    current = { "schema" => 1, "id" => "x", "file" => "a.mp4",
                "invented_by_another_client" => { "nested" => true } }

    merged = S.merge(current, { "title" => "A title" })

    assert_equal({ "nested" => true }, merged["invented_by_another_client"])
    assert_equal "A title", merged["title"]
  end

  test "merging is field by field, so a concurrent write is not clobbered" do
    # The page was rendered when the sidecar had no location. Someone else
    # added one while the form sat open. Saving a title must not erase it --
    # which is why the write re-reads first and merges rather than PUTting the
    # object it loaded.
    fresh_from_bucket = { "schema" => 1, "id" => "x", "file" => "a.mp4", "location" => "Added meanwhile" }

    merged = S.merge(fresh_from_bucket, { "title" => "My title" })

    assert_equal "Added meanwhile", merged["location"]
    assert_equal "My title", merged["title"]
  end

  test "clearing a field removes it rather than storing an empty string" do
    current = { "schema" => 1, "title" => "Old", "notes" => "Some notes" }

    merged = S.merge(current, { "title" => "", "notes" => nil })

    assert_not merged.key?("title")
    assert_not merged.key?("notes")
  end
end
