{
  description = "Python development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python312;
        pythonPackages = python.pkgs;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pythonPackages.pip
          ];

          shellHook = ''
            echo "Python ${python.version} development environment"
            
            # Create and activate virtual environment if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment..."
              ${python}/bin/python -m venv .venv
            fi
            
            source .venv/bin/activate
            
            # Upgrade pip
            pip install --upgrade pip > /dev/null
            
            echo "Virtual environment activated"
            echo "Use 'pip install -r requirements.txt' to install dependencies"
          '';
        };
      }
    );
}