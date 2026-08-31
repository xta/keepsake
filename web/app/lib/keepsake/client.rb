module Keepsake
  # Picks a backend for a library.
  #
  # Every outbound request in this app goes through one of these, which is what
  # makes `EndpointGuard` a boundary rather than a suggestion.
  module Client
    module_function

    def for(library)
      library.provider == "local" ? LocalClient.new(library) : S3Client.new(library)
    end
  end
end
