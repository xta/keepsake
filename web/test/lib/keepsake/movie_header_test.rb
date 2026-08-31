require "test_helper"

class Keepsake::MovieHeaderTest < ActiveSupport::TestCase
  setup do
    @user = User.create!(email_address: "mvhd@example.com", password: "password123")
    @library = @user.libraries.create!(
      label: "Headers", provider: "local",
      bucket: Rails.root.join("test/fixtures/library").to_s,
      access_key_id: "k", secret_access_key: "s"
    )
  end

  test "reads a runtime out of an mp4 header without downloading the file" do
    reader = Keepsake::RangeReader.new(@library.client, "media/2026/piano-recital.mp4")
    header = Keepsake::MovieHeader.read(reader)

    assert_equal 4.0, header.duration_s
    # The whole point: a header read is a couple of small ranged requests, not
    # a download. It stays cheap when the file is four gigabytes.
    assert_operator reader.requests, :<=, 2
  end

  test "returns nothing for a container it does not understand" do
    %w[ media/2026/scan-1985.avi media/2026/family-photo.heic ].each do |key|
      reader = Keepsake::RangeReader.new(@library.client, key)
      assert_nil Keepsake::MovieHeader.read(reader), "#{key} is not ISO base media format"
    end
  end

  test "a header that cannot be parsed is nil, never an exception" do
    # A sweep must not stop because one file was written by something creative.
    reader = Keepsake::RangeReader.new(@library.client, "media/2026/does-not-exist.mp4")
    assert_nothing_raised { Keepsake::MovieHeader.read(reader) }
  end

  test "an implausible creation date is discarded rather than recorded" do
    assert_nil Keepsake::MovieHeader.creation_date(0)
    assert_nil Keepsake::MovieHeader.creation_date(-1)
    # A stamp in the future is a broken clock or a misparse, not a fact.
    assert_nil Keepsake::MovieHeader.creation_date(99_999_999_999)
    assert_equal "2026-05-01", Keepsake::MovieHeader.creation_date(
      (Time.utc(2026, 5, 1) - Time.utc(1904, 1, 1)).to_i
    )
  end
end
