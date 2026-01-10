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
        python = pkgs.python314;
        pythonPackages = python.pkgs;
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = [
            python
            pythonPackages.pip
            pkgs.stdenv.cc.cc.lib
            
            # GTK3 and all dependencies
            pkgs.gtk3
            pkgs.gobject-introspection
            pkgs.pango
            pkgs.cairo
            pkgs.gdk-pixbuf
            pkgs.librsvg  # Add SVG support for gdk-pixbuf
            pkgs.harfbuzz
            pkgs.atk
            pkgs.glib
            
            # Python GTK bindings
            pythonPackages.pygobject3
            pythonPackages.pycairo
          ];

          shellHook = ''
            echo "Python ${python.version} development environment"
            
            # Create and activate virtual environment if it doesn't exist
            if [ ! -d .venv ]; then
              echo "Creating virtual environment..."
              ${python}/bin/python -m venv .venv --system-site-packages
            fi
            
            source .venv/bin/activate
            
            # Set LD_LIBRARY_PATH
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath [
              pkgs.stdenv.cc.cc.lib
            ]}:$LD_LIBRARY_PATH"
            
            # Build comprehensive GI_TYPELIB_PATH
            export GI_TYPELIB_PATH="${pkgs.gtk3}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.pango.out}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.cairo}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.gdk-pixbuf}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.harfbuzz}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.atk}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.glib}/lib/girepository-1.0"
            export GI_TYPELIB_PATH="$GI_TYPELIB_PATH:${pkgs.gobject-introspection}/lib/girepository-1.0"
            
            # Set GDK_PIXBUF_MODULE_FILE so SVG support works
            export GDK_PIXBUF_MODULE_FILE="${pkgs.librsvg.out}/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache"
            
            # Upgrade pip
            pip install --upgrade pip > /dev/null
            
            echo "Virtual environment activated"
            echo "Use 'pip install -r requirements.txt' to install dependencies"
          '';
        };
      }
    );
}