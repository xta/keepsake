require "test_helper"

class LibraryTest < ActiveSupport::TestCase
  setup { @user = User.create!(email_address: "lib@example.com", password: "password123") }

  test "pasted values are cleaned up rather than failing obscurely later" do
    library = @user.libraries.new(
      label: "  Family  ", provider: "b2",
      # The whole endpoint, pasted into the region field.
      region: "https://s3.us-west-001.backblazeb2.com",
      bucket: "s3://my-bucket/",
      # A newline picked up with a copied key otherwise surfaces only as
      # SignatureDoesNotMatch, a long way from the field that caused it.
      access_key_id: " key123 \n", secret_access_key: "  sec456  "
    )

    assert library.valid?, library.errors.full_messages.join("; ")
    assert_equal "Family", library.label
    assert_equal "us-west-001", library.region
    assert_equal "my-bucket", library.bucket
    assert_equal "https://s3.us-west-001.backblazeb2.com", library.endpoint
    assert_equal "key123", library.access_key_id
    assert_equal "sec456", library.secret_access_key
  end

  test "a bare host endpoint gets https rather than a rejection" do
    library = @user.libraries.new(
      label: "O", provider: "other", endpoint: "s3.us-west-001.backblazeb2.com/",
      region: "us-west-001", bucket: "b", access_key_id: "k", secret_access_key: "s"
    )
    assert library.valid?, library.errors.full_messages.join("; ")
    assert_equal "https://s3.us-west-001.backblazeb2.com", library.endpoint
  end

  test "a region that is not a region fails on the form, not inside the AWS SDK" do
    library = @user.libraries.new(
      label: "B", provider: "other", endpoint: "https://s3.us-west-001.backblazeb2.com",
      region: "not a region!", bucket: "b", access_key_id: "k", secret_access_key: "s"
    )
    assert_not library.valid?
    assert_match(/should look like/, library.errors[:region].join)
  end

  test "prefixes are stored in one shape" do
    %w[ media media/ /media ].each do |input|
      library = @user.libraries.new(prefix: input)
      library.valid?
      assert_equal "media/", library.prefix, "#{input.inspect} should normalise"
    end
  end

  test "the secret is never exposed, only hinted" do
    library = @user.libraries.create!(
      label: "S", provider: "local", bucket: Rails.root.join("test/fixtures/library").to_s,
      access_key_id: "k", secret_access_key: "abcdef123456"
    )
    assert_equal "••••••••3456", library.secret_hint
    assert_not_includes LibrarySerializer.call(library).to_s, "abcdef123456"
  end
end
